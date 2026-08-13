import time
import random
from functools import wraps

def retry_on_429(max_retries=3, initial_delay=2):
    """Decorator to retry function on 429 Resource Exhausted errors."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            delay = initial_delay
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    error_str = str(e)
                    # Check for 429 error code or "RESOURCE_EXHAUSTED"
                    if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                        if attempt == max_retries:
                            print(f"Max retries exceeded for 429 error: {e}")
                            raise
                        
                        sleep_time = delay + random.uniform(0, 1)
                        print(f"Rate limit hit (429). Retrying in {sleep_time:.2f}s...")
                        time.sleep(sleep_time)
                        delay *= 2  # Exponential backoff
                    else:
                        raise # Re-raise other errors
            return None # Should not be reached
        return wrapper
    return decorator

def register_skill(func):
    """
    Decorator to mark a function as a skill accessible by the AI.
    """
    func._is_skill = True
    return func

def skill(name=None, description=None, parameters=None):
    """
    Decorator to register a function as an AI skill with explicit metadata.
    """
    def decorator(func):
        func._is_skill = True
        func._skill_name = name or func.__name__
        func._skill_description = description or func.__doc__
        func._skill_parameters = parameters or {}
        return func
    return decorator

