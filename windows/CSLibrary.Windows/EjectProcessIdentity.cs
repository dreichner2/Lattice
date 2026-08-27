using System.Globalization;

namespace CSLibrary.Windows;

internal sealed record EjectProcessIdentity(
    int ProcessId,
    long StartTimeUtcTicks)
{
    internal string Encode() =>
        $"{ProcessId.ToString(CultureInfo.InvariantCulture)}:{StartTimeUtcTicks.ToString(CultureInfo.InvariantCulture)}";

    internal static EjectProcessIdentity Parse(string value)
    {
        var separator = value.IndexOf(':');
        if (separator <= 0 || separator == value.Length - 1)
            throw new ArgumentException("A tracked eject process identity is invalid.");
        if (!int.TryParse(
                value.AsSpan(0, separator),
                NumberStyles.None,
                CultureInfo.InvariantCulture,
                out var processId)
            || processId <= 0
            || !long.TryParse(
                value.AsSpan(separator + 1),
                NumberStyles.None,
                CultureInfo.InvariantCulture,
                out var startTimeUtcTicks)
            || startTimeUtcTicks <= 0)
        {
            throw new ArgumentException("A tracked eject process identity is invalid.");
        }
        return new EjectProcessIdentity(processId, startTimeUtcTicks);
    }
}
