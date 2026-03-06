
"""
omero_tools.py
Reusable tools for connecting to OMERO and retrieving images.
"""

import threading
import atexit
import getpass
import numpy as np
import time
from omero.gateway import BlitzGateway

__all__ = ["connect_to_omero", "get_omero_image"]

def connect_to_omero(username, host, port, password=None, secure=True):
    """
    Connect to OMERO server and keep connection alive.

    Args:
        username (str): OMERO username.
        host (str): OMERO server host.
        port (int): OMERO server port.
        password (str, optional): OMERO password. If None, prompt user.
        secure (bool): Use secure connection.

    Returns:
        BlitzGateway: Connected OMERO gateway object.
    """
    if password is None:
        password = getpass.getpass(f'Enter OMERO password for username {username}: ')
    conn = BlitzGateway(
        username,
        password,
        host=host,
        port=port,
        secure=secure
    )
    if not conn.connect():
        raise ConnectionError(f"Could not connect to OMERO server at {host}:{port}.")
    print(f"Connected to OMERO server at \"{host}\" port \"{port}\" as username \"{username}\".")

    stop_keepalive = threading.Event()
    def keep_connection_alive(conn, stop_event, interval=60):
        while not stop_event.wait(interval):
            try:
                conn.keepAlive()
            except Exception:
                break
    th_ka = threading.Thread(target=keep_connection_alive, args=(conn, stop_keepalive, 60), daemon=True)
    th_ka.start()

    def cleanup():
        stop_keepalive.set()
        th_ka.join(timeout=2)
        try:
            conn.close()
        except Exception:
            pass
    atexit.register(cleanup)
    return conn

def get_omero_image(conn, image_id, channels=None, t=0, order="ZCYX"):
    """
    Retrieve image data from OMERO.

    Args:
        conn (BlitzGateway): OMERO connection object.
        image_id (str|int): OMERO image ID.
        channels (list|int|None): Channels to fetch. None for all.
        t (int): Timepoint.
        order (str): Output array order, "ZCYX" or "CZYX".

    Returns:
        tuple: (image array, image name)
    """
    img = conn.getObject("Image", str(image_id))
    img_name = img.getName()
    print(f"Fetching {img_name}")
    start_time = time.time()
    pixels = img.getPrimaryPixels()
    sizeZ = int(img.getSizeZ())
    sizeC = int(img.getSizeC())
    if channels is None:
        channels = list(range(sizeC))
    elif isinstance(channels, int):
        channels = [channels]
    else:
        channels = list(channels)
    zct_list = [(z, c, t) for z in range(sizeZ) for c in channels]
    planes = list(pixels.getPlanes(zct_list))
    if not planes:
        arr = np.empty((0, 0, 0, 0))
    else:
        stacked = np.stack(planes, axis=0)
        y, x = stacked.shape[1], stacked.shape[2]
        arr = stacked.reshape((sizeZ, len(channels), y, x))
        if order == "CZYX":
            arr = arr.transpose((1, 0, 2, 3))  # (C, Z, Y, X)
        elif order != "ZCYX":
            raise ValueError("order must be 'ZCYX' or 'CZYX'")
    elapsed = time.time() - start_time
    print(f"Image fetched from OMERO in {elapsed:.2f} sec")
    print("Image shape")
    print(f"\r shape: {arr.shape}")
    print(f"\r dtype: {arr.dtype}")
    return arr, img_name
