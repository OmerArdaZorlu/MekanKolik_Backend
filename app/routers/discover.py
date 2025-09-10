from fastapi import FastAPI, Depends, File, HTTPException,APIRouter, Query,Security, WebSocket, WebSocketDisconnect
import httpx
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import TypeAdapter
from sqlalchemy import inspect,func
from sqlalchemy.orm import selectinload
from app import models
from database import get_db
from fastapi import HTTPException
from sqlalchemy.orm import Session

###
from schemas.models import Business, BusinessDB, TagsDB,Search
from db.database import SessionLocal
###

from schemas.business import BusinessOut,BusinessTagOut
from schemas.discover import Search
from models import Business , CampaignBusiness



discover = APIRouter()

def sqlalchemy_to_dict(obj):
    return {c.key: getattr(obj, c.key) for c in inspect(obj).mapper.column_attrs}

@discover.get("/nearby/{userId}")
def get_nearby(
    userId: int, 
    longitude: float, 
    latitude: float,
    db: Session = Depends(get_db)  # Sync session
):
    try:
        # SQLAlchemy 1.x style query
        businesses = db.query(models.Business).filter(
            func.ST_DistanceSphere(
                func.ST_MakePoint(models.Business.longitude, models.Business.latitude),
                func.ST_MakePoint(longitude, latitude)
            ) <= 10000
        ).all()

        return [{
            "business": Business(**sqlalchemy_to_dict(biz)),
            "tags": [],
            "images": []
        } for biz in businesses]

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(500, detail=str(e))

@discover.post("/home/{UserId}/search")
async def postSearch(
    search: Search,
    UserId: int,
    latitude: float = Query(...),
    longitude: float = Query(...),
):
    async with SessionLocal() as session:
        query = select(BusinessDB).outerjoin(BusinessDB.tags).options(selectinload(BusinessDB.images))
        
        query = query.filter(
            func.ST_DistanceSphere(
                func.ST_MakePoint(BusinessDB.longitude, BusinessDB.latitude),
                func.ST_MakePoint(longitude, latitude)
            ) <= search.distance,
            BusinessDB.stars >= search.stars,
            BusinessDB.AvgPrice <= search.AvgPrice
        )
        
        if search.tags is not None and len(search.tags) > 0:
            query = query.filter(TagsDB.tag.in_(search.tags))
        
        query = query.distinct()
        
        results = await session.execute(query)
        businesses = results.scalars().all()

        return [
            {"business": Business.from_orm(business)}
            for business in businesses
        ]

@discover.get("/home/{id}")
async def getBusiness(id : int):
    async with SessionLocal() as session:

        result = await session.execute(
            select(BusinessDB)
            .options(selectinload(BusinessDB.images))
            .where(BusinessDB.id == id)
        )

        businessDB : BusinessDB = result.scalar_one_or_none()

        if not businessDB:
            raise HTTPException(status_code=400, detail="Business not found")

    return {"business":Business.from_orm(businessDB)}

@discover.websocket("/ws/route/{business_id}")
async def route_websocket(websocket: WebSocket, business_id: int):
    await websocket.accept()
    try:
        async with SessionLocal() as session:
            result = await session.execute(
                select(BusinessDB).where(BusinessDB.id == business_id)
            )
            business = result.scalar_one_or_none()

            if not business:
                await websocket.send_json({"error": "Business not found"})
                await websocket.close()
                return

            dest_lat = business.latitude
            dest_lon = business.longitude

        while True:
            data = await websocket.receive_json()
            user_lat = data.get("latitude")
            user_lon = data.get("longitude")

            if user_lat is None or user_lon is None:
                await websocket.send_json({"error": "Missing coordinates"})
                continue

            osrm_url = (
                f"http://router.project-osrm.org/route/v1/driving/"
                f"{user_lon},{user_lat};{dest_lon},{dest_lat}"
                f"?overview=full&geometries=geojson"
            )

            async with httpx.AsyncClient() as client:
                response = await client.get(osrm_url)
                if response.status_code == 200:
                    route = response.json()
                    await websocket.send_json(route)
                else:
                    await websocket.send_json({"error": "Route fetch failed"})

    except WebSocketDisconnect:
        print(" Client disconnected.")