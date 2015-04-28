#!/usr/bin/env python
# Software License Agreement (BSD License)

import time
import rospy
from mavros.msg import OverrideRCIn
from mavros.srv import CommandBool
from mavros.srv import SetMode
from rospy.core import rospydebug
from RcMessage import RcMessage
from mavros.msg import State
from Configuration import Configuration

config = Configuration("NavConfig.json")
#FlightMode class : encapsulates all mode related operations of the drone
#To be further implemented
class Navigator:
    __rcMessage = None
    __armingService = None
    __setModeService = None
    __rcOverrideTopic = None
    __humanOverrideFlag = False
    __humanOverrideDefault = None
    __humanOverrideElapsedTime = None
    __navigatorParams = None

    #Register to all needed topics/services for this object
    #init a RcMessage as a member for this class, to be able to control whats published
    #on the rc/override topic
    def __init__(self):
        self.__navigatorParams = Configuration.GetConfigurationSection("params")
        self.__humanOverrideDefault = self.__navigatorParams["HumanOverrideDefault"]
        self.__setModeService = rospy.ServiceProxy('/mavros/set_mode',SetMode)
        self.__armingService = rospy.ServiceProxy('/mavros/cmd/arming', CommandBool)
        self.__rcOverrideTopic = rospy.Publisher('/mavros/rc/override',OverrideRCIn,queue_size = 10) #TBD : how to determine queue size
        self.__rcOverrideListener = rospy.Subscriber('/mavros/rc/override',OverrideRCIn,self.__HumanOverrideCallback)
        self.__rcMessage = RcMessage()

    #Arm: arm/disarm the drone
    #param : armDisarmBool - true for arm, false for disarm
    #return value : success/failure
    def Arm(self, armDisarmBool):
        self.__rcMessage.PrepareForArming()
        self.PublishRCMessage(self.__rcMessage.GetRcMessage())
        time.sleep(1) #TBD : is this necessary? need to check if topic was grabbed
        try:
            return self.__armingService(armDisarmBool)
        except rospy.ServiceException as ex:
            print("Service did not process request: " + str(ex))
            return False

    #GetCurrentMode : get the current mode of flight as mode object
    #return value : State.mode object
    def GetCurrentMode(self):
        return State(rospy.wait_for_message('/mavros/state', State, timeout=1)).mode

    #SetCurrentMode : set the current mode of flight
    #param : mode - the requested mode of flight as string
    #return value : success/failure
    def SetCurrentMode(self, mode):
        return self.__setModeService(base_mode=0, custom_mode=mode)
    
    #PublishRCMessage : publish new message to rc/override topic to set rc channels
    #params : roll, pitch, throttle, yaw as integer values between 1000 to 2000
    def PublishRCMessage(self, roll, pitch, throttle, yaw):
        if self.__IsPublishAllowed():
            self.__rcMessage.SetRoll(roll)
            self.__rcMessage.SetPitch(pitch)
            self.__rcMessage.SetThrottle(throttle)
            self.__rcMessage.SetYaw(yaw)
            self.__rcOverrideTopic.publish(self.__rcMessage.GetRcMessage())

    #PublishRCMessage : publish new message to rc/override topic to set rc channels
    #params : RcMessage object with all channels set
    def PublishRCMessage(self, rcMessage):
        if self.__IsPublishAllowed():
            self.__rcOverrideTopic.publish(rcMessage)

    #HumanOverrideCallback : Constantly checking rc/override HumanOverride channel and maintaining a
    #boolean flag according to that
    def __HumanOverrideCallback(self, data):
        self.__humanOverrideElapsedTime = time.time()
        val = data.channels[self.__navigatorParams["HumanOverrideChannel"]]
        threshHold = self.__navigatorParams["HumanOverrideThreshold"]
        if (val < self.__humanOverrideDefault - threshHold) or (val > self.__humanOverrideDefault + threshHold):
            self.__humanOverrideFlag = False

    #IsPublishAllowed : Make all safety checks in this method.
    #return value : True/False according to all safety checks.
    def __IsPublishAllowed(self):
        if not self.__humanOverrideFlag or (time.time() - self.__humanOverrideElapsedTime > 2):
            print "Human override channel activated, publish disabled"
            #TBD: define logger behavior here
            return False
        else:
            return True






