from suu_scrape.core.base import PluginBase

class HelloWorldPlugin(PluginBase):
    """
    A simple example plugin that prints to stdout.
    """
    
    def run(self, data: any, context: dict) -> None:
        print("Hello from the HelloWorldPlugin!")
        print(f"Data received: {data}")
        print(f"Context received: {context}")

    def setup(self, config: dict) -> None:
        print(f"HelloWorldPlugin setup with config: {config}")
