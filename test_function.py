import json as _json

def test():
    def salvage_and_clean_json(text_to_parse: str) -> list:
        parsed = None
        try:
            parsed = _json.loads(text_to_parse)
        except Exception:
            clean_t = text_to_parse.strip()
            last_brace = clean_t.rfind('}')
            if last_brace != -1:
                if clean_t.startswith("{"):
                    for suffix in ["}", "]}", "]} }", "] }"]:
                        try:
                            parsed = _json.loads(clean_t[:last_brace + 1] + suffix)
                            break
                        except Exception:
                            continue
                else:
                    try:
                        parsed = _json.loads(clean_t[:last_brace + 1] + ']')
                    except Exception:
                        pass
        return parsed

    print(salvage_and_clean_json('{"a": 1}'))

test()
