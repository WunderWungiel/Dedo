import math

def format_size(size_bytes, decimals=2):

    if size_bytes == 0:
        return "0 bytes"
    
    power = 1024
    units = ["bytes", "KB", "MB", "GB", "TB", "PB"]

    i = int(math.floor(math.log(size_bytes, power)))
    size = size_bytes / (power ** i)
    return f"{int(size)} {units[i]}" if size.is_integer() else f"{size_bytes / (power ** i):.{decimals}f} {units[i]}"
