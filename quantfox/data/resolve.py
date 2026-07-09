import re
from typing import Literal, Optional

from pydantic import BaseModel

AssetType = Literal["otc_fund", "gold"]
_GOLD = {"gold", "黄金", "au99.99", "au9999"}


class Asset(BaseModel):
    symbol: str
    name: Optional[str] = None
    type: AssetType


def resolve(query: str) -> Asset:
    q = query.strip()
    if q.lower() in _GOLD:
        return Asset(symbol="Au99.99", type="gold", name="黄金Au99.99")
    if re.fullmatch(r"\d{6}", q):
        return Asset(symbol=q, type="otc_fund")
    raise ValueError(f"无法识别的标的: {query!r}（支持 6 位基金代码或 '黄金'/'gold'）")
