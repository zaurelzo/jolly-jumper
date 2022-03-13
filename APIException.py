class APIBadRequestError(Exception):
    code = 400
    description = "User provide not valid argument"

class StravaApiException(Exception):
    def __init__(self, message, code):
        super().__init__(message)
        self.code = code

if __name__ == '__main__':
    try:
        raise StravaApiException("exceptiodsdn",200)
    except StravaApiException as e:
        print(e.args[0])
        print(e.code)

