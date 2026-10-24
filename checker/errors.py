class CheckerError(Exception):
    pass


class BlockedError(CheckerError):
    pass


class FetchError(CheckerError):
    pass


class ParseError(CheckerError):
    pass


class NotifyError(CheckerError):
    pass
