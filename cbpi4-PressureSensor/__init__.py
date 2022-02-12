
# -*- coding: utf-8 -*-
import os
from aiohttp import web
import logging
from unittest.mock import MagicMock, patch
import asyncio
import random
from cbpi.api import *
from cbpi.api.dataclasses import NotificationAction, NotificationType

##### Sensor requirements #####
import time
import board
import busio
import adafruit_ads1x15.ads1115 as ADS
from adafruit_ads1x15.analog_in import AnalogIn
###############################

logger = logging.getLogger(__name__)


@parameters([
    Property.Select(label="ADSchannel", options=[0,1,2,3], description="Enter channel-number of ADS1x15"),
    Property.Select("sensorType", options=["Voltage","Digits","Pressure","Liquid Level","Volume"], description="Select which type of data to register for this sensor"),
    Property.Select("pressureType", options=["kPa","PSI"]),
    Property.Number("voltLow", configurable=True, default_value=0, description="Pressure Sensor minimum voltage, usually 0"),
    Property.Number("voltHigh", configurable=True, default_value=5, description="Pressure Sensor maximum voltage, usually 5"),
    Property.Number("pressureLow", configurable=True, default_value=0, description="Pressure value at minimum voltage, value in kPa"),
    Property.Number("pressureHigh", configurable=True, default_value=10, description="Pressure value at maximum voltage, value in kPa"),
    Property.Number("sensorHeight", configurable=True, default_value=0, description="Location of Sensor from the bottom of the kettle in inches"),
    Property.Number("kettleDiameter", configurable=True, default_value=0, description="Diameter of kettle in inches")
])


class PressureSensor(CBPiSensor):
    
    def __init__(self, cbpi, id, props):
        super(PressureSensor, self).__init__(cbpi, id, props)
        self.value = 0
        # Variables to be used with calculations
        self.GRAVITY = 9.807
        self.PI = 3.1415
        # Conversion values
        self.kpa_psi = 0.145
        self.bar_psi = 14.5038
        self.inch_mm = 25.4
        self.gallons_cubicinch = 231
        
        self.sensorHeight = float(self.props.get("sensorHeight", 0))
        self.kettleDiameter = float(self.props.get("kettleDiameter", 0))
        self.ADSchannel = int(self.props.get("ADSchannel", 0))
        self.pressureHigh = self.convert_pressure(int(self.props.get("pressureHigh", 10)))
        self.pressureLow = self.convert_pressure(int(self.props.get("pressureLow", 0)))
        #logging.info('Pressure values - low: %s , high: %s' % ((pressureLow), (pressureHigh)))
        # We need the coefficients to calculate pressure for the next step
        # Using Y=MX+B where X is the volt output difference, M is kPa/volts or pressure difference / volt difference
        #  B is harder to explain, it's the offset of the voltage & pressure, ex:
        #    if volts were 1-5V and pressure was 0-6kPa
        #    since volts start with 1, there is an offset
        #    We calculate a value of 1.5kPa/V, therefore 1V = -1.5
        #    if the output of the sensor was 0-5V there would be no offset
        self.calcX = int(self.props.get("voltHigh", 5)) - int(self.props.get("voltLow", 0))
        #logging.info('calcX value: %s' % (calcX))
        self.calcM = (self.pressureHigh - self.pressureLow) / self.calcX
        #logging.info('calcM value: %s' % (calcM))
        self.calcB = 0
        if int(self.props.get("voltLow", 0)) > 0:
            self.calcB = (-1 * int(self.props.get("voltLow", 0))) * self.calcM
        #logging.info('calcB value: %s' % (calcB))
        
    
    def convert_pressure(self, value):
        if self.props.get("pressureType", "kPa") == "PSI":
            return value * self.kpa_psi
        else:
            return value
    
    def convert_bar(self, value):
        if self.props.get("pressureType", "kPa") == "PSI":
            return value / self.bar_psi
        else:
            return value / 100

    async def run(self):
        
        while self.running is True:
            
            # Create the I2C bus
            i2c = busio.I2C(board.SCL, board.SDA)
            
            # Create the ADS object using the I2C bus
            ads = ADS.ADS1115(i2c)
            
            # Create single-ended input on channel specified
            if self.ADSchannel == 0:
                chan = AnalogIn(ads, ADS.P0)
            elif self.ADSchannel == 1:
                chan = AnalogIn(ads, ADS.P1)
            elif self.ADSchannel == 2:
                chan = AnalogIn(ads, ADS.P2)
            elif self.ADSchannel == 3:
                chan = AnalogIn(ads, ADS.P3)
                
            pressureValue = (self.calcM * chan.voltage) + self.calcB    # "%.6f" % ((calcM * voltage) + calcB)
            #logging.info("pressureValue: %s" % (pressureValue))    #debug or calibration
            
            # Time to calculate the other data values
            
            # Liquid Level is calculated by H = P / (SG * G). Assume the SG of water is 1.000
            #   this is true for water at 4C
            #   note: P needs to be in BAR and H value will need to be multiplied by 100,000 to get mm
            liquidLevel = ((self.convert_bar(pressureValue) / self.GRAVITY) * 100000) / self.inch_mm
            if liquidLevel > 0.49:
                liquidLevel += self.sensorHeight
            
            # Volume is calculated by V = PI (r squared) * height
            kettleRadius = self.kettleDiameter / 2
            radiusSquared = kettleRadius * kettleRadius
            volumeCI = self.PI * radiusSquared * liquidLevel
            volume = volumeCI / self.gallons_cubicinch

            if self.props.get("sensorType", "Liquid Level") == "Voltage":
                self.value = chan.voltage
            elif self.props.get("sensorType", "Liquid Level") == "Digits":
                self.value = chan.value
            elif self.props.get("sensorType", "Liquid Level") == "Pressure":
                self.value = pressureValue
            elif self.props.get("sensorType", "Liquid Level") == "Liquid Level":
                self.value = liquidLevel
            elif self.props.get("sensorType", "Liquid Level") == "Volume":
                self.value = volume
            else:
                self.value = chan.voltage
            
            self.push_update(self.value)
            await asyncio.sleep(1)
    
    def get_state(self):
        return dict(value=self.value)


def setup(cbpi):
    cbpi.plugin.register("PressureSensor", PressureSensor)
    pass