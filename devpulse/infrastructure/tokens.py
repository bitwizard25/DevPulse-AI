"""Conservative content estimate. Framing/thinking overhead uses a separate reserve."""


class ConservativeTokenCounter:
    name = 'utf8-byte-upper-estimate-v1'
    exact = False

    def count(self, text: str) -> int:
        return len(text.encode('utf-8'))
