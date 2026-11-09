import numpy as np

def valid_vector(value):
    try:
        a = np.asarray(value, dtype=float)
        return a.ndim == 1 and a.size > 0 and np.isfinite(a).all() and np.linalg.norm(a) > 0
    except (TypeError, ValueError):
        return False
