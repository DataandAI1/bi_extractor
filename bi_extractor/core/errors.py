"""Custom exception hierarchy for bi_extractor."""


class BiExtractorError(Exception):
    """Base exception for all bi_extractor errors."""


class ParserError(BiExtractorError):
    """Raised when a parser encounters an error during extraction."""

    def __init__(self, message: str, file_path: str = "", parser_name: str = ""):
        self.file_path = file_path
        self.parser_name = parser_name
        super().__init__(message)


class UnsupportedFormatError(BiExtractorError):
    """Raised when no parser is registered for a file extension."""

    def __init__(self, extension: str):
        self.extension = extension
        super().__init__(f"No parser registered for extension: {extension}")


class DependencyError(BiExtractorError):
    """Raised when a required optional dependency is not available."""

    def __init__(self, package: str, install_hint: str = ""):
        self.package = package
        self.install_hint = install_hint
        msg = f"Required dependency not available: {package}"
        if install_hint:
            msg += f". Install with: {install_hint}"
        super().__init__(msg)


class DuplicateExtensionError(BiExtractorError):
    """Raised when two parsers try to register for the same file extension."""

    def __init__(self, extension: str, existing_parser: str, new_parser: str):
        self.extension = extension
        self.existing_parser = existing_parser
        self.new_parser = new_parser
        super().__init__(
            f"Extension '{extension}' already registered by {existing_parser}, "
            f"cannot register {new_parser}"
        )
