import sys

from zz.multiplayer.websocket_server import main as multiplayer_main
from zz.web.server import main as web_main

if __name__ == "__main__":
    if "--multiplayer" in sys.argv:
        sys.argv = [sys.argv[0], *[arg for arg in sys.argv[1:] if arg != "--multiplayer"]]
        multiplayer_main()
    else:
        web_main()
