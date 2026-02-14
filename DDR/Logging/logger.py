import logging 
import os
from datetime import datetime

LOG_FILE =f"{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.log"

logs_path=os.path.join(os.getcwd(),'logs',LOG_FILE)
os.makedirs(logs_path, exist_ok=True)

lOG_FILE_PATH=os.path.join(logs_path,LOG_FILE)

logging.basicConfig(
    filename=lOG_FILE_PATH,
    level=logging.INFO,
    format='[%(asctime)s ] %(levelname)s - %(module)s - %(message)s',
)
    
