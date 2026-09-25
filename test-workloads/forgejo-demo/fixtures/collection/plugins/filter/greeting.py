"""A small, dependency-free greeting filter for the agent demo."""


def greeting(name):
    """Return a friendly greeting with surrounding name whitespace removed."""
    return f"Hello, {name.strip()}!"


class FilterModule:
    """Expose the filter to Ansible as demo.greetings.greeting."""

    def filters(self):
        return {"greeting": greeting}
