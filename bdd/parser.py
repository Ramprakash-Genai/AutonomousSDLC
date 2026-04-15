def parse_bdd(text):
    steps = []
    lines = text.split("\n")
    for line in lines:
        line = line.strip()
        if line.startswith(("Given", "When", "Then", "And")):
            steps.append(line)
    return steps
