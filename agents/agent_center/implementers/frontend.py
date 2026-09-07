"""FrontendImplementer — scoped to AGENT_FE_ROOT."""

from __future__ import annotations

from config import AGENT_FE_ROOT
from agent_center.implementers.base import BaseImplementer


class FrontendImplementer(BaseImplementer):
    layer = "frontend"
    allowed_root = AGENT_FE_ROOT
