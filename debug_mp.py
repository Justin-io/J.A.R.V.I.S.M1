import mediapipe as mp
try:
    print(mp.solutions)
    print("Import successful")
except AttributeError as e:
    print(f"Error: {e}")
    # Inspect what 'mediapipe' actually is
    import inspect
    print(f"File: {inspect.getfile(mp)}")
