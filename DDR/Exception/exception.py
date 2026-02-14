import sys
import traceback


class DDRException(Exception):
    def __init__(self, error_message, error_details: sys = None):
        super().__init__(str(error_message))
        self.error_message = str(error_message)
        self.lineno = "Unknown"
        self.file_name = "Unknown"

        # safely extract traceback info if available
        try:
            if error_details:
                _, _, exc_tb = error_details.exc_info()
                if exc_tb is not None:
                    self.lineno = exc_tb.tb_lineno
                    self.file_name = exc_tb.tb_frame.f_code.co_filename
        except Exception:
            pass

    def __str__(self):
        return (
            f"Error occurred in python script [{self.file_name}] "
            f"line number [{self.lineno}] error message [{self.error_message}]"
        )