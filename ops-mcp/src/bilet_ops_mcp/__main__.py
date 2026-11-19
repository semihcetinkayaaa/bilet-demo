"""Çalıştırma: python -m bilet_ops_mcp  (MCP adresi: http://<host>:<port>/mcp)"""

import logging

import uvicorn

from bilet_ops_mcp.config import settings
from bilet_ops_mcp.server import build_app

logging.basicConfig(level=logging.INFO, format='{"level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}')

if __name__ == "__main__":
    uvicorn.run(build_app(), host="0.0.0.0", port=settings.port, proxy_headers=True, forwarded_allow_ips="*",
                access_log=False)
