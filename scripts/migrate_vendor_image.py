import sys
sys.path.append('.')
import asyncio
from sqlalchemy import text
from app.database import engine, Base

async def run():
    async with engine.begin() as conn:
        dialect_name = conn.dialect.name
        
        # Vendor image_url column
        image_exists = False
        if dialect_name == "postgresql":
            res = await conn.execute(text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name='vendors' AND column_name='image_url'"
            ))
            image_exists = res.scalar() is not None
        else:
            res = await conn.execute(text("PRAGMA table_info(vendors)"))
            columns = res.fetchall()
            image_exists = any(col[1] == "image_url" for col in columns)

        if not image_exists:
            print("Adding image_url column to vendors table")
            await conn.execute(text("ALTER TABLE vendors ADD COLUMN image_url VARCHAR(512)"))
        
        # Requisition JSON items column
        items_exists = False
        if dialect_name == "postgresql":
            res = await conn.execute(text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name='requisitions' AND column_name='items'"
            ))
            items_exists = res.scalar() is not None
        else:
            res = await conn.execute(text("PRAGMA table_info(requisitions)"))
            columns = res.fetchall()
            items_exists = any(col[1] == "items" for col in columns)

        if not items_exists:
            print("Adding items column to requisitions table")
            if dialect_name == "postgresql":
                await conn.execute(text("ALTER TABLE requisitions ADD COLUMN items JSONB"))
            else:
                await conn.execute(text("ALTER TABLE requisitions ADD COLUMN items JSON"))

if __name__ == '__main__':
    asyncio.run(run())
