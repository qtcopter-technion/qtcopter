#!/usr/bin/env python2

'''
Find the target from contour detection and the contours nesting.

Usage:
    ./scan_find.py <image/camera> [--debug] [--gain <value>]
'''

import cv2
import cv
import numpy as np
import random
import argparse
from ptgrey import PTGreyCamera
import flycapture2 as fc2
from time import time
from math import sin, cos, pi
import math

def show_img(img, wait=True, title='bah'):
    while max(img.shape[:2]) > 500:
        img = cv2.pyrDown(img)
    #ratio = 500./max(img.shape)
    #cv2.resize(img, 

    cv2.imshow(title, img)
    if cv2.waitKey(1)&0xff == ord('q'):
        raise KeyboardInterrupt()
    if wait:
        while True:
            if cv2.waitKey(0)&0xff==ord('q'):
                break
        cv2.destroyAllWindows()


def dist(a, b):
    return math.sqrt((a[0]-b[0])**2 + (a[1]-b[1])**2)

class Circle:
    def __init__(self, center, radius, matching_lines=None):
        self.center = center
        self.radius = radius
        self.matching_lines = matching_lines
    def __repr__(self):
        return '<Circle (%.2f, %.2f) %.2f>' % (self.center[0], self.center[1], self.radius)
    def similar(self, other):
        # check if another circle is similar to self.
        # True if centers are within radius/5, and radiuses are within 20%.
        p = 1.2
        avg_radius = (other.radius+self.radius)/2.
        maxdist = avg_radius/5.

        r = 1.0*other.radius/self.radius
        return ((1/p) < r) & (r < p) & (dist(self.center, other.center) < maxdist)

class ScanFind:
    def __init__(self, center_black, number_of_rings, debug=True):
        self._center_black = center_black
        self._number_of_rings = number_of_rings
        self._canny_threshold1 = 200
        self._canny_threshold2 = 20
        self._debug = debug
        self._min_radius = 20
        #self._max_radius = max(image.shape)
        self._scan_jump = self._min_radius/4.
        self._near_threshold = self._scan_jump*4
    def _near(self, a, b):
        " Are two points one near another? "
        return dist(a, b)<self._near_threshold
    def find_target(self, image):
        '''
        Return the center and the diameter of the target in pixel coordinates
        as tuple ((x, y), diameter).
        '''
        # resize input image, assuming target takes at least 1/2 of the frame.
        self.resize = 400
        orig_shape = image.shape[:2]
        while min(image.shape[:2]) > self.resize:
            image = cv2.pyrDown(image)
        ratio = 1.*image.shape[0]/orig_shape[0]

        center, radius = self.find_circles(image)
        if center is None:
            if self._debug:
                print 'center:', (None, None)
            return (None, None)
        if self._debug:
            print 'center:', (float(center[0])/ratio, float(center[1])/ratio), 2*float(radius)/ratio
        return (float(center[0])/ratio, float(center[1])/ratio), 2*float(radius)/ratio

    def find_circles(self, image):
        image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        # blur kernel about 20 for 1000x1000px, 10 for 500x500, 5 for 250x250
        #blurk = max(image.shape)/50
        blurk = max(image.shape)/100
        if ~blurk&1:
            blurk += 1
        image = cv2.medianBlur(image, blurk)

        can = cv2.Canny(image, self._canny_threshold1, self._canny_threshold2)

        if self._debug:
            show_img(can, wait=False, title='canny')
            #show_img(can, wait=True, title='canny'+ str(random.randint(1, 10000000)))

        # get distance matrix (distance to nearest 1)
        distance = cv2.distanceTransform(255-can, cv.CV_DIST_L2, 3)
        points = [_[::-1] for _ in np.transpose(can.nonzero())]
        if len(points) == 0:
            return None, None

        # find horizontal and vertical lines
        # look for one less ring, because we can't rely on the outer ring's
        # edge being identified correctly. This happens because the outer ring
        # is black. If the outer ring is close to the target's background
        # border, i.e. the background is very narrow, while the ground is dark,
        # we may not detect the edge correctly.
        circles_hor = self.find_lines(distance, image, lines=self._number_of_rings-1)
        circles_ver = self.find_lines(distance, image, lines=self._number_of_rings-1, transpose=True)

        # groupify horizontal found circles
        groups_hor = self.groupify(circles_hor)
        circles_hor = []
        for group in groups_hor:
            center = np.mean([c.center for c in group], axis=0)
            radius = np.mean([c.radius for c in group])
            circles_hor.append(Circle(center, radius))

        # groupify vertical found circles
        groups_ver = self.groupify(circles_ver)
        circles_ver = []
        for group in groups_ver:
            center = np.mean([c.center for c in group], axis=0)
            radius = np.mean([c.radius for c in group])
            circles_ver.append(Circle(center, radius))

        # find circles that are both in horizontal and vertical scan find
        good_circles = []
        for circle in circles_hor:
            # we can't use circle.similar() here because horizontal and vertical
            # circles are not necessarily with a similar radius if the camera is
            # not directly above target.
            near = filter(lambda c: self._near(c.center, circle.center), circles_ver)
            if len(near) == 0:
                continue
            
            group = [circle] + near
            center = np.mean([c.center for c in group], axis=0)
            radius = np.mean([c.radius for c in group])
            good_circles.append(Circle(center, radius, matching_lines=len(group)))

        good_circles = sorted(good_circles, key=lambda c: c.matching_lines, reverse=True)
        if len(good_circles) > 1:
            # TODO: select circle with most "lines"
            print 'WARNING: multiple circles..'

        if self._debug:
            for circle in good_circles:
                center = circle.center
                radius = circle.radius
                radius *= 1.0*self._number_of_rings/(self._number_of_rings-1)
                cv2.circle(image, tuple(map(int, center)), 4, 255, -1)
                cv2.circle(image, tuple(map(int, center)), int(radius), 255, 1)
            show_img(image, wait=False, title='scan lines')

        if len(good_circles) > 0:
            center, radius = good_circles[0].center, good_circles[0].radius
            # we searched for one less ring, scale the radius
            radius *= 1.0*self._number_of_rings/(self._number_of_rings-1)
            return center, radius
        return (None, None)

    def groupify(self, circles):
        circles = set(circles)

        groups = []
        while len(circles) > 0:
            before_len = len(circles)
            for group in groups:
                # find circles that are nearby/similar to our circle and group them.
                # the purpose is to group together circles that are nearly identic
                right  = max(group, key=lambda c: c.center[1])
                bottom = max(group, key=lambda c: c.center[0])
                last = set([right, bottom])
                close = set()
                for circle in last:
                    #close |= set(filter(lambda c: self._near(c.center, circle.center), circles))
                    close |= set(filter(circle.similar, circles))
                group |= close
                circles -= close
            if before_len == len(circles):
                # we didn't add any circles to the groups. create new group.
                group = set([circles.pop()])
                groups.append(group)
                circles -= group

        return groups

    #@profile
    def find_lines(self, distance, image, lines=5, transpose=False):
        ''' find scan lines corresponding to target.
        lines parameter specifies how many circles we are looking for.
        5 lines means inner + 4 outer circles.
        as we fly lower, we can't see the whole target, so we search for less circles.
        '''
        if transpose:
            distance = distance.transpose()
        circles = []
        count = np.ceil(distance.shape[0]/self._scan_jump)
        for y in np.linspace(0, distance.shape[0]-1, num=count):
            xx = np.arange(distance.shape[1])
            #yy = np.tile(int(y), len(xx))
            z = distance[y, xx]

            # indexes of borders
            zi = (z==0).nonzero()[0]

            # distances between borders
            d = zi[1:]-zi[:-1]
            di = zi[:-1] # indexes of distances

            # remove intervals of length 1 (for when we catch border multiple times)
            d, di = d[d!=1], di[d!=1]

            # TODO: filter out additional bad distances (too small/big),
            # according to height?
            if len(d) < lines:
                # not enough lines, scan next line
                continue

            d = d.astype(np.float)
            #print 'di, z, d:', di, z, d

            a0, a1, a2, a3, a4 = d[:-4], d[1:-3], d[2:-2], d[3:-1],d[4:]
            #avg = (a0+a1+a2+a3+a4)/6 # (a4 (a0) is twice the length)

            a_list = [d[i:i-(lines-1)] for i in range(lines-1)] + [d[lines-1:]]
            avg = sum(a_list)/(1+lines) # inner line/circle is twice the size

            a_list1 = [d[i:i-(lines-1)] for i in range(lines-1)] + [d[lines-1:]/2]
            a_list2 = [d[:-lines+1]/2] + [d[i:i-(lines-1)] for i in range(1, lines-1)] + [d[lines-1:]]
            #print 'avg:', avg, 'low/high:', avg*0.8, avg*1.2

            # find 5 consecutive values that are around the average of the 5 values
            p = 1.2*avg
            p1 = avg/1.2

            # ratio 1: 1/1/1/1/2 (outer to inner ring)
            #r1 = (p1<a0) & (a0<p) &\
            #     (p1<a1) & (a1<p) &\
            #     (p1<a2) & (a2<p) &\
            #     (p1<a3) & (a3<p) &\
            #     (p1<a4/2) & (a4/2<p)

            r1 = (p1 < a_list1) & (a_list1 < p)
            r1 = np.all(r1, axis=0)

            # ratio 2: 2/1/1/1/1 (inner to outer ring)
            #r2 = (p1<a0/2) & (a0/2<p) &\
            #     (p1<a1) & (a1<p) &\
            #     (p1<a2) & (a2<p) &\
            #     (p1<a3) & (a3<p) &\
            #     (p1<a4) & (a4<p)
            r2 = (p1 < a_list2) & (a_list2 < p)
            r2 = np.all(r2, axis=0)

            for i in r1.nonzero()[0]:
                start = di[i]
                radius = avg[i]*lines
                # TODO: what's the best estimate for the center?
                center = (start+radius, y)
                line_end = (int(start), int(y))
                if transpose:
                    center = center[::-1]
                    line_end = tuple(line_end[::-1])

                circles.append(Circle(center, radius))

                if self._debug:
                    cv2.line(image, tuple(map(int, center)), line_end, 255, 1)
                    cv2.circle(image, tuple(map(int, center)), 2, 255, -1)

            for i in r2.nonzero()[0]:
                end = di[i+lines-1]+d[i+lines-1]
                radius = avg[i]*lines
                center = (end-radius, y)
                line_end = (int(end), int(y))
                if transpose:
                    center = center[::-1]
                    line_end = tuple(line_end[::-1])

                circles.append(Circle(center, radius))

                if self._debug:
                    cv2.line(image, tuple(map(int, center)), line_end, (255, 0, 0), 1)
                    cv2.circle(image, tuple(map(int, center)), 2, (255, 0, 0), -1)

        if self._debug:
            show_img(image, wait=False, title='debug2?')
        return circles

    def check_circles(self, distance, center, img):
        count = 50.
        radiuses = np.array([], dtype=float)
        for alpha in np.linspace(0, 2*pi, num=count, endpoint=False):
            rad = self.check_circles_line(distance, center, alpha, img)
            if rad is not None:
                radiuses = np.append(radiuses, rad)
        #print 'radiuses:', radiuses
        # TODO: check if radiuses are mostly same
        # NOTE: check if radiuses are roughly the same will work if the checked
        # center is almost correct. however, what if we miss the center slightly?
        # hm.. then we should have at least 2 directions correct (if we missed the center
        # a bit up, then still up/down directions should yield a line with reoccuring radius distances
        # but left/right will be quite wrong.) what to do?
        good = (0.8*np.median(radiuses)<radiuses)&(radiuses<1.2*np.median(radiuses))
        good = radiuses[good]
        print 'count:', count, 'radiuses:', len(radiuses), 'good:', len(good), 'med:', np.median(radiuses), 'avg:', np.average(radiuses)
         
        if len(good) > 0.25*count:
            return center, np.median(radiuses)
        return None, None

if __name__ == '__main__':

    parser = argparse.ArgumentParser(description='')
    parser.add_argument('--shutter', default=10, type=float, help='shutter time (10 ms default for indoor, 1-2 ms is fine for outside)')
    parser.add_argument('--gain', default=0, type=float, help='gain')
    parser.add_argument('--debug', action='store_true', help='debug')
    parser.add_argument('--quite', action='store_true', help='quite')
    parser.add_argument('-t', '--threshold', default=100, help='')
    parser.add_argument('cam', nargs='*', help='image file or camera')

    args = parser.parse_args()

    if args.cam:
        import cProfile
        finder = ScanFind(True, 5, debug=args.debug)
        for image in args.cam:
            image = cv2.imread(image)
            center, size = finder.find_target(image)
            #cProfile.run("center, size = finder.find_target(image)")
            print 'center:', center
            if center is not None:
                cv2.circle(image, tuple(map(int, center)), 10, (0, 255, 255), -1)
                cv2.circle(image, tuple(map(int, center)), int(size), (0, 255, 255), 3)
                if not args.quite:
                    show_img(image, wait=False)
            else:
                print 'could not find target'
                if not args.quite:
                    show_img(image, wait=False)
    else:
        c = PTGreyCamera()
        # set manual values
        c.set_property_manual(fc2.AUTO_EXPOSURE, 0) # exposure = 0, we don't modify this. I'm not sure, but it had no effect.
        c.set_property_manual(fc2.SHUTTER, args.shutter) # 10ms shutter (1/100, hopefully fast enough)
        # if frame_rate is too high, it is set to maximum :)
        c.set_property_manual(fc2.FRAME_RATE, 100) # maximum framerate
        c.set_property_manual(fc2.GAIN, args.gain)
        c.print_infos()

        c.start_capture()
        finder = ScanFind(True, 5, debug=args.debug)
        
        try:
            while True:
                img = c.get_frame()
                t = time()
                center, size = finder.find_target(img)
                t = time()-t
                print 'time:', t, 1/t, 'fps'
                if center is not None:
                    cv2.circle(img, (int(center[0]), int(center[1])), 10, (255, 255, 0), -1)
                show_img(img, wait=False, title='img_target')
        except KeyboardInterrupt:
            print 'bye..'
