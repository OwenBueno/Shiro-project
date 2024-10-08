import os

def delete_file(filename):
    try:
        if os.path.exists(filename):
            os.remove(filename)
            print(f"Deleted file: {filename}")
        else:
            print(f"File not found: {filename}")
    except Exception as e:
        print(f"Error deleting file {filename}: {e}")
