using Microsoft.Win32.SafeHandles;
using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.InteropServices;

namespace CSLibrary.Windows;

internal static class WindowsProcessTree
{
    private const uint Th32csSnapProcess = 0x00000002;
    private const int MaximumTrackedProcesses = 64;
    private const int ErrorNoMoreFiles = 18;

    internal static IReadOnlyList<EjectProcessIdentity> Capture(Process rootProcess)
    {
        ArgumentNullException.ThrowIfNull(rootProcess);
        var rootProcessId = rootProcess.Id;
        var rootIdentity = new EjectProcessIdentity(
            rootProcessId,
            rootProcess.StartTime.ToUniversalTime().Ticks);

        var childrenByParent = SnapshotChildrenByParent();
        var processIds = new HashSet<int> { rootProcessId };
        var pending = new Queue<int>();
        pending.Enqueue(rootProcessId);
        while (pending.TryDequeue(out var parentProcessId))
        {
            if (!childrenByParent.TryGetValue(parentProcessId, out var children)) continue;
            foreach (var childProcessId in children)
            {
                if (!processIds.Add(childProcessId)) continue;
                if (processIds.Count > MaximumTrackedProcesses)
                {
                    throw new InvalidOperationException(
                        "Lattice found an unexpected number of local-service processes and did not eject the drive.");
                }
                pending.Enqueue(childProcessId);
            }
        }

        var identities = new List<EjectProcessIdentity>(processIds.Count);
        foreach (var processId in processIds.OrderBy(value => value))
        {
            if (processId == rootProcessId)
            {
                identities.Add(rootIdentity);
                continue;
            }
            try
            {
                using var process = Process.GetProcessById(processId);
                if (!process.HasExited)
                {
                    var startTimeUtcTicks = process.StartTime.ToUniversalTime().Ticks;
                    if (startTimeUtcTicks >= rootIdentity.StartTimeUtcTicks)
                    {
                        identities.Add(new EjectProcessIdentity(
                            processId,
                            startTimeUtcTicks));
                    }
                }
            }
            catch (ArgumentException)
            {
                // The process exited after the Toolhelp snapshot.
            }
            catch (InvalidOperationException)
            {
                // The process exited while its exact identity was read.
            }
            catch (Win32Exception error)
            {
                throw new InvalidOperationException(
                    $"Lattice could not verify local-service process {processId} before ejecting the drive.",
                    error);
            }
        }
        return identities;
    }

    private static Dictionary<int, List<int>> SnapshotChildrenByParent()
    {
        using var snapshot = CreateToolhelp32Snapshot(Th32csSnapProcess, 0);
        if (snapshot.IsInvalid)
            throw new Win32Exception(Marshal.GetLastWin32Error());

        var entry = new ProcessEntry32
        {
            Size = checked((uint)Marshal.SizeOf<ProcessEntry32>()),
            ExecutableFile = string.Empty,
        };
        if (!Process32First(snapshot, ref entry))
        {
            var error = Marshal.GetLastWin32Error();
            if (error == ErrorNoMoreFiles) return new Dictionary<int, List<int>>();
            throw new Win32Exception(error);
        }

        var childrenByParent = new Dictionary<int, List<int>>();
        do
        {
            var processId = checked((int)entry.ProcessId);
            var parentProcessId = checked((int)entry.ParentProcessId);
            if (processId > 0 && parentProcessId > 0)
            {
                if (!childrenByParent.TryGetValue(parentProcessId, out var children))
                {
                    children = new List<int>();
                    childrenByParent[parentProcessId] = children;
                }
                children.Add(processId);
            }
            entry.Size = checked((uint)Marshal.SizeOf<ProcessEntry32>());
        }
        while (Process32Next(snapshot, ref entry));

        var lastError = Marshal.GetLastWin32Error();
        if (lastError != 0 && lastError != ErrorNoMoreFiles) throw new Win32Exception(lastError);
        return childrenByParent;
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct ProcessEntry32
    {
        internal uint Size;
        internal uint Usage;
        internal uint ProcessId;
        internal UIntPtr DefaultHeapId;
        internal uint ModuleId;
        internal uint ThreadCount;
        internal uint ParentProcessId;
        internal int PriorityClassBase;
        internal uint Flags;

        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 260)]
        internal string ExecutableFile;
    }

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern SafeFileHandle CreateToolhelp32Snapshot(uint flags, uint processId);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool Process32First(
        SafeFileHandle snapshot,
        ref ProcessEntry32 entry);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool Process32Next(
        SafeFileHandle snapshot,
        ref ProcessEntry32 entry);
}
