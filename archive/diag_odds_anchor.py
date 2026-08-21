with open("match_predictor_app.py", "r") as f:
    content = f.read()

start = content.find("def fetch_fixture_odds(")
end = content.find("\ndef fetch_fixture_injuries(")
snippet = content[start:end]
print(repr(snippet))
