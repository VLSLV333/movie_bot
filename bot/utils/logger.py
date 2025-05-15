import logging
from logging.handlers import RotatingFileHandler
import inspect

class Logger:
    def __init__(self, log_file: str = 'bot.log'):
        # Get the name of the calling module dynamically
        caller_frame = inspect.stack()[1]
        module = inspect.getmodule(caller_frame[0])
        logger_name = module.__name__ if module else "movie_bot_logger"

        self.logger = logging.getLogger(logger_name)
        self.logger.setLevel(logging.INFO)

        # Avoid adding multiple handlers if already exists
        if not self.logger.handlers:
            # File handler with rotation
            file_handler = RotatingFileHandler(log_file, maxBytes=5 * 1024 * 1024, backupCount=3)
            file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            file_handler.setFormatter(file_formatter)

            # Console handler with color
            console_handler = logging.StreamHandler()
            console_formatter = self.ColorFormatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            console_handler.setFormatter(console_formatter)

            # Add handlers
            self.logger.addHandler(file_handler)
            self.logger.addHandler(console_handler)

    class ColorFormatter(logging.Formatter):
        COLORS = {
            logging.DEBUG: "\033[37m",      # White
            logging.INFO: "\033[32m",       # Green
            logging.WARNING: "\033[33m",    # Yellow
            logging.ERROR: "\033[31m",      # Red
            logging.CRITICAL: "\033[41m",   # Red background
        }
        RESET = "\033[0m"

        def format(self, record):
            log_color = self.COLORS.get(record.levelno, self.RESET)
            message = super().format(record)
            return f"{log_color}{message}{self.RESET}"

    def get_logger(self):
        return self.logger
