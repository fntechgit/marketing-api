import re


class HexColorValidator:
    pattern = re.compile(r'^#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$')

    @staticmethod
    def is_valid(color):
        return bool(HexColorValidator.pattern.match(color))
