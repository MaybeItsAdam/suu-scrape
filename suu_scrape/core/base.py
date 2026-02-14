from abc import ABC, abstractmethod

class PluginBase(ABC):
    """
    Abstract base class for suu-scrape Plugins.
    All plugins must inherit from this class.
    """

    @abstractmethod
    def run(self, data: any, context: dict) -> None:
        """
        Main execution method for the plugin.
        
        :param data: The data scraped by the scraper.
        :param context: Dictionary containing shared context/data (e.g. database connection, config).
        """
        pass

    def setup(self, config: dict) -> None:
        """
        Optional setup method called before run.
        
        :param config: Configuration dictionary for this specific plugin.
        """
        pass
