class RetryableDownloadError(Exception):
    """Use this to indicate network or temporary issues that deserve a retry."""
    pass


# List of exceptions we consider retryable
RETRYABLE_EXCEPTIONS = (
    TimeoutError,
    ConnectionError,
    OSError,  # network socket issues
    # aiohttp-specific
    ImportError,  # Just in case aiohttp isn't loaded yet (safe fail)
)

# If you're using aiohttp, you can extend this with more specific ones:
try:
    import aiohttp
    RETRYABLE_EXCEPTIONS += (
        aiohttp.ClientError,
        aiohttp.ClientConnectionError,
        aiohttp.ClientPayloadError,
        aiohttp.ServerTimeoutError,
    )
except ImportError:
    pass
