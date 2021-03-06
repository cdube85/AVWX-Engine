"""
Aviation weather report parsing library
"""

# stdlib
from abc import abstractmethod
from datetime import datetime
# module
from avwx import metar, taf, airep, pirep, translate, summary, speech, service, static, structs
from avwx.core import valid_station
from avwx.structs import Station


class Report(object):
    """
    Base report to take care of service assignment and station info
    """

    #: UTC Datetime object when the report was last updated
    last_updated: datetime = None

    #: The unparsed report string. Fetched on update()
    raw: str = None

    #: ReportData dataclass of parsed data values and units. Parsed on update()
    data: structs.ReportData = None

    #: ReportTrans dataclass of translation strings from data. Parsed on update()
    translations: structs.ReportTrans = None

    #: Units inferred from the station location and report contents
    units: structs.Units = None

    _station_info: Station = None

    def __init__(self, station: str):
        # Raises a BadStation error if needed
        valid_station(station)

        #: Service object used to fetch the report string
        self.service = service.get_service(station)(self.__class__.__name__.lower())
        
        #: 4-character ICAO station ident code the report was initialized with
        self.station = station

    @property
    def station_info(self) -> Station:
        """
        Provide basic station info

        Raises a BadStation exception if the station's info cannot be found
        """
        if self._station_info is None:
            self._station_info = Station.from_icao(self.station)
        return self._station_info

    @abstractmethod
    def _post_update(self):
        pass

    @classmethod
    def from_report(cls, report: str) -> 'Report':
        """
        Returns an updated report object based on an existing report
        """
        obj = cls(report[:4])
        obj.update(report)
        return obj

    def update(self, report: str = None) -> bool:
        """
        Updates raw, data, and translations by fetching and parsing the report

        Can accept a report string to parse instead

        Returns True if a new report is available, else False
        """
        if not report:
            report = self.service.fetch(self.station)
        if not report or report == self.raw:
            return False
        self.raw = report
        self._post_update()
        return True

    async def async_update(self) -> bool:
        """
        Async version of update
        """
        report = await self.service.async_fetch(self.station)
        if not report or report == self.raw:
            return False
        self.raw = report
        self._post_update()
        return True

    def __repr__(self) -> str:
        return f'<avwx.{self.__class__.__name__} station={self.station}>'


class Metar(Report):
    """
    Class to handle METAR report data
    """

    def _post_update(self):
        self.data, self.units = metar.parse(self.station, self.raw)
        self.translations = translate.metar(self.data, self.units)
        self.last_updated = datetime.utcnow()

    @property
    def summary(self) -> str:
        """
        Condensed report summary created from translations
        """
        if not self.translations:
            self.update()
        return summary.metar(self.translations)

    @property
    def speech(self) -> str:
        """
        Report summary designed to be read by a text-to-speech program
        """
        if not self.data:
            self.update()
        return speech.metar(self.data, self.units)


class Taf(Report):
    """
    Class to handle TAF report data
    """

    def _post_update(self):
        self.data, self.units = taf.parse(self.station, self.raw)
        self.translations = translate.taf(self.data, self.units)
        self.last_updated = datetime.utcnow()

    @property
    def summary(self) -> [str]:
        """
        Condensed summary for each forecast created from translations
        """
        if not self.translations:
            self.update()
        return [summary.taf(trans) for trans in self.translations.forecast]

    @property
    def speech(self) -> str:
        """
        Report summary designed to be read by a text-to-speech program
        """
        if not self.data:
            self.update()
        return speech.taf(self.data, self.units)

class Reports(object):
    """
    Base class containing multiple reports
    """

    #: UTC Datetime object when the report was last updated
    last_updated: datetime = None

    #: Provide basic station info if given at init
    station_info: Station = None

    raw_reports: [str] = None
    data: [structs.ReportData] = None
    units: structs.Units = structs.Units(**static.NA_UNITS)

    def __init__(self, station: str = None, lat: float = None, lon: float = None):
        if station:
            station = Station.from_icao(station)
            self.station_info = station
            lat = station.latitude
            lon = station.longitude
        elif lat is None or lon is None:
            raise ValueError('No station or valid coordinates given')
        self.lat = lat
        self.lon = lon
        self.service = service.NOAA('aircraftreport')

    def _post_update(self):
        pass

    @staticmethod
    def _report_filter(reports: [str]) -> [str]:
        """
        Applies any report filtering before updating raw_reports
        """
        return reports

    def update(self, reports: [str] = None) -> bool:
        """
        Updates raw_reports and data by fetch recent aircraft reports

        Can accept a list report strings to parse instead

        Returns True if new reports are available, else False
        """
        if not reports:
            reports = self.service.fetch(lat=self.lat, lon=self.lon)
            if not reports:
                return False
        if isinstance(reports, str):
            reports = [reports]
        if reports == self.raw_reports:
            return False
        self.raw_reports = self._report_filter(reports)
        self._post_update()
        return True

    async def async_update(self) -> bool:
        """
        Async version of update
        """
        reports = await self.service.async_fetch(lat=self.lat, lon=self.lon)
        if not reports or reports == self.raw_reports:
            return False
        self.raw_reports = reports
        self._post_update()
        return True


class Pireps(Reports):
    """
    Class to handle pilot report data
    """

    data: [structs.PirepData] = None

    @staticmethod
    def _report_filter(reports: [str]) -> [str]:
        """
        Removes AIREPs before updating raw_reports
        """
        return [r for r in reports if not r.startswith('ARP')]

    def _post_update(self):
        self.data = []
        for report in self.raw_reports:
            self.data.append(pirep.parse(report))


class Aireps(Reports):
    """
    Class to handle aircraft report data
    """

    data: [structs.AirepData] = None

    @staticmethod
    def _report_filter(reports: [str]) -> [str]:
        """
        Removes PIREPs before updating raw_reports
        """
        return [r for r in reports if r.startswith('ARP')]

    def _post_update(self):
        self.data = []
        for report in self.raw_reports:
            airep.parse(report)
