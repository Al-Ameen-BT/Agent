from analytics_agent.database import init_db, engine
from sqlalchemy import text

def test_connection():
    try:
        # Test basic connection
        with engine.connect() as conn:
            result = conn.execute(text("SELECT version();"))
            version = result.scalar()
            print(f"✅ Successfully connected to PostgreSQL!")
            print(f"📊 PostgreSQL Version: {version}")
        
        # Initialize tables
        print("\nInitializing database tables...")
        init_db()
        print("✅ Tables created successfully (if they didn't exist).")
        print("Schema 'ticket_analytics' is ready for batch jobs.")
        
    except Exception as e:
        print(f"❌ Failed to connect to PostgreSQL or create tables.")
        print(f"Error details: {e}")

if __name__ == "__main__":
    test_connection()
