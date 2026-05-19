import logging
from bot import ProjectCreatorBot

logging.basicConfig(level=logging.INFO)
if __name__ == "__main__":
    bot = ProjectCreatorBot()
    bot.run()