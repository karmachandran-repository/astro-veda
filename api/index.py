import os
import sys

# Ensure parent directory (project root) is in the search path for Vercel Serverless Functions
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from web_server import app
