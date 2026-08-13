import psutil
import typing as t
from .decorators import register_skill

@register_skill
def get_memory_usage() -> t.Tuple[float, float, float]:
    """
    Returns the current system's memory usage statistics.

    Returns:
        tuple: A tuple containing:
            - total memory usage percentage (float).
            - used memory in GB (float).
            - free memory in GB (float).
    """
    vm = psutil.virtual_memory()
    total_usage_percent = float(vm.percent)
    used_gb = float(vm.used / (1024 ** 3))
    free_gb = float(vm.available / (1024 ** 3))
    return total_usage_percent, used_gb, free_gb

if __name__ == '__main__':
    usage_percent, used_gb, free_gb = get_memory_usage()
    print(f"Total Memory Usage: {usage_percent:.2f}%")
    print(f"Used Memory: {used_gb:.2f} GB")
    print(f"Free Memory: {free_gb:.2f} GB")