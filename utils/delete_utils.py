import os

def delete_file(filename, silent=False):
    """
    Deletes a file if it exists.

    Args:
        filename (str): The path to the file to delete.
        silent (bool): If True, suppress error messages.

    Returns:
        bool: True if the file was successfully deleted, False otherwise.
    """
    try:
        if os.path.exists(filename):
            os.remove(filename)
            if not silent:
                print(f"Deleted file: {filename}")
            return True
        else:
            if not silent:
                print(f"File not found: {filename}")
            return False
    except Exception as e:
        if not silent:
            print(f"Error deleting file {filename}: {e}")
        return False
