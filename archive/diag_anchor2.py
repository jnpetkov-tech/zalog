with open("match_predictor_app.py", "r") as f:
    content = f.read()

start = content.find("def top_pick_with_code(")
end = content.find("\ndef compute_grouped_markets(")
if end == -1:
    end = start + 2000
snippet = content[start:end]
print(repr(snippet))
