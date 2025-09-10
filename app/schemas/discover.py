from typing import List, Optional
from pydantic import BaseModel

class Search(BaseModel):
    distance: Optional[int]
    tags : Optional[List[str]]
    stars : Optional[float]
    AvgPrice : Optional[int]