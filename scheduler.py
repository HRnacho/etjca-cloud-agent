# scheduler.py
# Copiare il contenuto dall'artifact corrispondente
# Contenuto per scheduler.py:
#!/usr/bin/env python3
import os
import schedule
import time
from datetime import datetime
import logging
from etjca_cloud_agent import CloudLeadAgent

logging.basicConfig(level=logging.INFO)

def main():
    agent = CloudLeadAgent()
    
    schedule.every().day.at("08:00").do(agent.run_full_cycle)
    schedule.every().day.at("14:00").do(agent.email_manager.schedule_follow_ups)
    schedule.every().monday.at("09:00").do(agent.generate_report_only)
    
    logging.info("🕐 Scheduler ETJCA avviato")
    
    while True:
        try:
            schedule.run_pending()
            time.sleep(60)
        except Exception as e:
            logging.error(f"Errore scheduler: {e}")
            time.sleep(300)

if __name__ == "__main__":
    main()