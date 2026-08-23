using Microsoft.Win32.SafeHandles;
using System.ComponentModel;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;

namespace CSLibrary.Windows;

internal enum PnpVetoType
{
    PNP_VetoTypeUnknown = 0,
    PNP_VetoLegacyDevice = 1,
    PNP_VetoPendingClose = 2,
    PNP_VetoWindowsApp = 3,
    PNP_VetoWindowsService = 4,
    PNP_VetoOutstandingOpen = 5,
    PNP_VetoDevice = 6,
    PNP_VetoDriver = 7,
    PNP_VetoIllegalDeviceRequest = 8,
    PNP_VetoInsufficientPower = 9,
    PNP_VetoNonDisableable = 10,
    PNP_VetoLegacyDriver = 11,
    PNP_VetoInsufficientRights = 12,
    PNP_VetoAlreadyRemoved = 13,
}

internal sealed record NativeEjectTarget(
    string LibraryRoot,
    string DriveRoot,
    string VolumeName,
    string RelativeLibraryPath,
    uint DeviceInstance,
    string DeviceInstanceId,
    uint DeviceNumber);

internal sealed record NativeEjectResult(
    bool Success,
    uint ConfigurationManagerResult,
    PnpVetoType VetoType,
    string VetoName)
{
    internal string FailureDetail
    {
        get
        {
            var vetoName = string.IsNullOrWhiteSpace(VetoName) ? "(none reported)" : VetoName;
            return $"Veto type: {VetoType} ({(int)VetoType})\n"
                + $"Veto name: {vetoName}\n"
                + $"Configuration Manager result: 0x{ConfigurationManagerResult:X8}";
        }
    }
}

internal static class NativeDriveEjector
{
    private const uint CrSuccess = 0;
    private const uint CrRemoveVetoed = 0x00000017;
    private const int ErrorNoMoreItems = 259;
    private const int ErrorInsufficientBuffer = 122;
    private const uint DigcfPresent = 0x00000002;
    private const uint DigcfDeviceInterface = 0x00000010;
    private const uint FileShareRead = 0x00000001;
    private const uint FileShareWrite = 0x00000002;
    private const uint FileShareDelete = 0x00000004;
    private const uint OpenExisting = 3;
    private const uint IOCTL_STORAGE_GET_DEVICE_NUMBER = 0x002D1080;
    private const int MaxPath = 260;
    private static readonly IntPtr InvalidHandleValue = new(-1);
    private static readonly Guid DiskInterfaceClass = new(
        "53F56307-B6BF-11D0-94F2-00A0C91EFB8B");

    internal static NativeEjectTarget ResolveTarget(string libraryRoot)
    {
        var source = Path.GetFullPath(libraryRoot);
        var driveRoot = Path.GetPathRoot(source);
        if (string.IsNullOrWhiteSpace(driveRoot)
            || driveRoot.Length < 3
            || !char.IsAsciiLetter(driveRoot[0])
            || driveRoot[1] != ':'
            || driveRoot[2] != Path.DirectorySeparatorChar)
        {
            throw new InvalidOperationException(
                "Windows safe eject requires a library on a drive-letter volume.");
        }

        driveRoot = $"{char.ToUpperInvariant(driveRoot[0])}:\\";
        var systemRoot = Path.GetPathRoot(Environment.SystemDirectory);
        if (string.Equals(driveRoot, systemRoot, StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidOperationException("Lattice will never eject the Windows system drive.");
        }

        var volumeName = GetVolumeName(driveRoot);
        var volumeDevice = QueryDeviceNumber(VolumeDevicePath(driveRoot));
        if (!string.IsNullOrWhiteSpace(systemRoot))
        {
            var systemDevice = QueryDeviceNumber(VolumeDevicePath(systemRoot));
            if (systemDevice.DeviceType == volumeDevice.DeviceType
                && systemDevice.DeviceNumber == volumeDevice.DeviceNumber)
            {
                throw new InvalidOperationException("Lattice will never eject the Windows system disk.");
            }
        }

        var diskDeviceInstance = FindDiskDeviceInstance(volumeDevice);
        var (usbDeviceInstance, usbDeviceInstanceId) = FindParentUsbDevice(diskDeviceInstance);
        var relativeLibraryPath = Path.GetRelativePath(driveRoot, source);
        if (!ExternalLibraryVolumeRecord.IsSafeRelativePath(relativeLibraryPath))
        {
            throw new InvalidOperationException(
                "The library path could not be safely recorded for drive reconnection.");
        }

        return new NativeEjectTarget(
            source,
            driveRoot,
            volumeName,
            relativeLibraryPath,
            usbDeviceInstance,
            usbDeviceInstanceId,
            volumeDevice.DeviceNumber);
    }

    internal static NativeEjectResult RequestEject(string deviceInstanceId)
    {
        if (string.IsNullOrWhiteSpace(deviceInstanceId)
            || !deviceInstanceId.StartsWith("USB\\", StringComparison.OrdinalIgnoreCase)
            || deviceInstanceId.StartsWith("USB\\ROOT_HUB", StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException(
                "The saved eject target is not a removable USB device.");

        var locateResult = CM_Locate_DevNodeW(out var deviceInstance, deviceInstanceId, 0);
        if (locateResult != CrSuccess)
            throw new InvalidOperationException(
                $"Windows could not locate the saved USB device (0x{locateResult:X8}). The drive was not ejected.");
        var actualDeviceInstanceId = GetDeviceInstanceId(deviceInstance);
        if (!string.Equals(actualDeviceInstanceId, deviceInstanceId, StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException(
                "The USB device identity changed before eject. Windows was not asked to remove it.");

        var vetoName = new StringBuilder(MaxPath);
        var result = CM_Request_Device_EjectW(
            deviceInstance,
            out var vetoType,
            vetoName,
            (uint)vetoName.Capacity,
            0);
        return new NativeEjectResult(
            result == CrSuccess,
            result,
            vetoType,
            vetoName.ToString());
    }

    internal static bool IsTransientCloseVeto(NativeEjectResult result) =>
        result.ConfigurationManagerResult == CrRemoveVetoed
        && result.VetoType is PnpVetoType.PNP_VetoPendingClose
            or PnpVetoType.PNP_VetoOutstandingOpen;

    internal static string GetVolumeName(string driveRoot)
    {
        var normalized = Path.EndsInDirectorySeparator(driveRoot)
            ? driveRoot
            : driveRoot + Path.DirectorySeparatorChar;
        var buffer = new StringBuilder(MaxPath + 1);
        if (!GetVolumeNameForVolumeMountPointW(normalized, buffer, (uint)buffer.Capacity))
            throw new Win32Exception(
                Marshal.GetLastWin32Error(),
                $"Windows could not identify the volume mounted at {normalized}.");
        return buffer.ToString();
    }

    private static string VolumeDevicePath(string driveRoot) =>
        $@"\\.\{char.ToUpperInvariant(driveRoot[0])}:";

    private static StorageDeviceNumber QueryDeviceNumber(string devicePath)
    {
        using var handle = CreateFileW(
            devicePath,
            0,
            FileShareRead | FileShareWrite | FileShareDelete,
            IntPtr.Zero,
            OpenExisting,
            0,
            IntPtr.Zero);
        if (handle.IsInvalid)
            throw new Win32Exception(
                Marshal.GetLastWin32Error(),
                $"Windows could not inspect storage device {devicePath}.");
        if (!DeviceIoControl(
                handle,
                IOCTL_STORAGE_GET_DEVICE_NUMBER,
                IntPtr.Zero,
                0,
                out var number,
                (uint)Marshal.SizeOf<StorageDeviceNumber>(),
                out var returned,
                IntPtr.Zero)
            || returned < (uint)Marshal.SizeOf<StorageDeviceNumber>())
        {
            throw new Win32Exception(
                Marshal.GetLastWin32Error(),
                $"Windows could not map storage device {devicePath} to its disk.");
        }
        return number;
    }

    private static uint FindDiskDeviceInstance(StorageDeviceNumber volumeDevice)
    {
        var interfaceClass = DiskInterfaceClass;
        var deviceInfoSet = SetupDiGetClassDevsW(
            ref interfaceClass,
            null,
            IntPtr.Zero,
            DigcfPresent | DigcfDeviceInterface);
        if (deviceInfoSet == InvalidHandleValue)
            throw new Win32Exception(
                Marshal.GetLastWin32Error(),
                "Windows could not enumerate disk devices.");

        try
        {
            for (uint index = 0; ; index++)
            {
                var interfaceData = new SpDeviceInterfaceData
                {
                    Size = (uint)Marshal.SizeOf<SpDeviceInterfaceData>(),
                };
                if (!SetupDiEnumDeviceInterfaces(
                        deviceInfoSet,
                        IntPtr.Zero,
                        ref interfaceClass,
                        index,
                        ref interfaceData))
                {
                    var error = Marshal.GetLastWin32Error();
                    if (error == ErrorNoMoreItems) break;
                    throw new Win32Exception(error, "Windows could not enumerate a disk interface.");
                }

                var deviceInfo = new SpDevinfoData
                {
                    Size = (uint)Marshal.SizeOf<SpDevinfoData>(),
                };
                _ = SetupDiGetDeviceInterfaceDetailW(
                    deviceInfoSet,
                    ref interfaceData,
                    IntPtr.Zero,
                    0,
                    out var requiredSize,
                    ref deviceInfo);
                var detailError = Marshal.GetLastWin32Error();
                if (requiredSize == 0 || detailError != ErrorInsufficientBuffer)
                {
                    throw new Win32Exception(
                        detailError,
                        "Windows could not size a disk interface path.");
                }

                var detailBuffer = Marshal.AllocHGlobal(checked((int)requiredSize));
                try
                {
                    Marshal.WriteInt32(detailBuffer, IntPtr.Size == 8 ? 8 : 6);
                    deviceInfo.Size = (uint)Marshal.SizeOf<SpDevinfoData>();
                    if (!SetupDiGetDeviceInterfaceDetailW(
                            deviceInfoSet,
                            ref interfaceData,
                            detailBuffer,
                            requiredSize,
                            out _,
                            ref deviceInfo))
                    {
                        throw new Win32Exception(
                            Marshal.GetLastWin32Error(),
                            "Windows could not read a disk interface path.");
                    }

                    var devicePath = Marshal.PtrToStringUni(IntPtr.Add(detailBuffer, sizeof(uint)));
                    if (string.IsNullOrWhiteSpace(devicePath)) continue;
                    StorageDeviceNumber diskDevice;
                    try
                    {
                        diskDevice = QueryDeviceNumber(devicePath);
                    }
                    catch (Win32Exception)
                    {
                        // An unrelated disk can disappear during enumeration.
                        continue;
                    }
                    if (diskDevice.DeviceType == volumeDevice.DeviceType
                        && diskDevice.DeviceNumber == volumeDevice.DeviceNumber)
                    {
                        return deviceInfo.DeviceInstance;
                    }
                }
                finally
                {
                    Marshal.FreeHGlobal(detailBuffer);
                }
            }
        }
        finally
        {
            _ = SetupDiDestroyDeviceInfoList(deviceInfoSet);
        }

        throw new InvalidOperationException(
            "Windows could not find the physical disk that contains the Lattice library.");
    }

    private static (uint DeviceInstance, string DeviceInstanceId) FindParentUsbDevice(
        uint diskDeviceInstance)
    {
        uint? selected = null;
        string? selectedId = null;
        var current = diskDeviceInstance;
        for (var depth = 0; depth < 32; depth++)
        {
            var deviceId = GetDeviceInstanceId(current);
            if (deviceId.StartsWith("USB\\ROOT_HUB", StringComparison.OrdinalIgnoreCase)) break;
            if (deviceId.StartsWith("USB\\", StringComparison.OrdinalIgnoreCase))
            {
                selected = current;
                selectedId = deviceId;
            }

            var parentResult = CM_Get_Parent(out var parent, current, 0);
            if (parentResult != CrSuccess) break;
            current = parent;
        }

        if (selected is null || string.IsNullOrWhiteSpace(selectedId))
        {
            throw new InvalidOperationException(
                "The library disk is not attached through a removable USB device. Lattice did not request ejection.");
        }
        return (selected.Value, selectedId);
    }

    private static string GetDeviceInstanceId(uint deviceInstance)
    {
        var sizeResult = CM_Get_Device_ID_Size(out var length, deviceInstance, 0);
        if (sizeResult != CrSuccess || length == 0 || length > 4096)
            throw new InvalidOperationException(
                $"Windows could not read a storage device identifier (0x{sizeResult:X8}).");
        var value = new StringBuilder(checked((int)length + 1));
        var result = CM_Get_Device_IDW(deviceInstance, value, (uint)value.Capacity, 0);
        if (result != CrSuccess)
            throw new InvalidOperationException(
                $"Windows could not read a storage device identifier (0x{result:X8}).");
        return value.ToString();
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct SpDeviceInterfaceData
    {
        internal uint Size;
        internal Guid InterfaceClassGuid;
        internal uint Flags;
        internal IntPtr Reserved;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct SpDevinfoData
    {
        internal uint Size;
        internal Guid ClassGuid;
        internal uint DeviceInstance;
        internal IntPtr Reserved;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct StorageDeviceNumber
    {
        internal uint DeviceType;
        internal uint DeviceNumber;
        internal uint PartitionNumber;
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern SafeFileHandle CreateFileW(
        string fileName,
        uint desiredAccess,
        uint shareMode,
        IntPtr securityAttributes,
        uint creationDisposition,
        uint flagsAndAttributes,
        IntPtr templateFile);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool DeviceIoControl(
        SafeFileHandle device,
        uint controlCode,
        IntPtr inputBuffer,
        uint inputBufferSize,
        out StorageDeviceNumber outputBuffer,
        uint outputBufferSize,
        out uint bytesReturned,
        IntPtr overlapped);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetVolumeNameForVolumeMountPointW(
        string volumeMountPoint,
        StringBuilder volumeName,
        uint bufferLength);

    [DllImport("setupapi.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern IntPtr SetupDiGetClassDevsW(
        ref Guid classGuid,
        string? enumerator,
        IntPtr parentWindow,
        uint flags);

    [DllImport("setupapi.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool SetupDiEnumDeviceInterfaces(
        IntPtr deviceInfoSet,
        IntPtr deviceInfoData,
        ref Guid interfaceClassGuid,
        uint memberIndex,
        ref SpDeviceInterfaceData deviceInterfaceData);

    [DllImport("setupapi.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool SetupDiGetDeviceInterfaceDetailW(
        IntPtr deviceInfoSet,
        ref SpDeviceInterfaceData deviceInterfaceData,
        IntPtr deviceInterfaceDetailData,
        uint deviceInterfaceDetailDataSize,
        out uint requiredSize,
        ref SpDevinfoData deviceInfoData);

    [DllImport("setupapi.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool SetupDiDestroyDeviceInfoList(IntPtr deviceInfoSet);

    [DllImport("cfgmgr32.dll")]
    private static extern uint CM_Get_Parent(
        out uint parentDeviceInstance,
        uint deviceInstance,
        uint flags);

    [DllImport("cfgmgr32.dll", CharSet = CharSet.Unicode)]
    private static extern uint CM_Locate_DevNodeW(
        out uint deviceInstance,
        string deviceInstanceId,
        uint flags);

    [DllImport("cfgmgr32.dll")]
    private static extern uint CM_Get_Device_ID_Size(
        out uint length,
        uint deviceInstance,
        uint flags);

    [DllImport("cfgmgr32.dll", CharSet = CharSet.Unicode)]
    private static extern uint CM_Get_Device_IDW(
        uint deviceInstance,
        StringBuilder buffer,
        uint bufferLength,
        uint flags);

    [DllImport("cfgmgr32.dll", CharSet = CharSet.Unicode)]
    private static extern uint CM_Request_Device_EjectW(
        uint deviceInstance,
        out PnpVetoType vetoType,
        StringBuilder vetoName,
        uint vetoNameLength,
        uint flags);
}
