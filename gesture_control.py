import cv2
import mediapipe as mp
import pyautogui
import math
import numpy as np
import threading
import time

class HandGestureController:
    def __init__(self):
        self.mp_hands = mp.solutions.hands
        self.hands = self.mp_hands.Hands(max_num_hands=1, min_detection_confidence=0.7)
        self.mp_draw = mp.solutions.drawing_utils
        self.screen_width, self.screen_height = pyautogui.size()
        self.running = False
        self.thread = None
        self.cap = None

        # Smooth movement variables
        self.plocX, self.plocY = 0, 0
        self.clocX, self.clocY = 0, 0
        self.smoothening = 5

    def get_distance(self, p1, p2):
        return math.hypot(p2[0] - p1[0], p2[1] - p1[1])

    def _run_loop(self):
        self.cap = cv2.VideoCapture(0)
        
        while self.running and self.cap.isOpened():
            success, img = self.cap.read()
            if not success:
                continue

            img = cv2.flip(img, 1) # Flip for natural movement
            h, w, c = img.shape
            img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            results = self.hands.process(img_rgb)

            if results.multi_hand_landmarks:
                for hand_lms in results.multi_hand_landmarks:
                    lm_list = []
                    for id, lm in enumerate(hand_lms.landmark):
                        lm_list.append([int(lm.x * w), int(lm.y * h)])

                    if len(lm_list) < 21:
                        continue

                    # 1. INDEX FINDER TO ACTIVATE MOUSE (Movement)
                    # Index tip (8), Middle tip (12)
                    index_x, index_y = lm_list[8]
                    thumb_x, thumb_y = lm_list[4]
                    
                    # Convert coordinates to screen size
                    # We map a smaller window of the cam to the screen to avoid reaching to edges
                    # Frame reduction (optional, but good for usability)
                    frame_r = 100 
                    x3 = np.interp(index_x, (frame_r, w - frame_r), (0, self.screen_width))
                    y3 = np.interp(index_y, (frame_r, h - frame_r), (0, self.screen_height))
                    
                    # Smoothening movement
                    self.clocX = self.plocX + (x3 - self.plocX) / self.smoothening
                    self.clocY = self.plocY + (y3 - self.plocY) / self.smoothening
                    
                    try:
                        pyautogui.moveTo(self.clocX, self.clocY)
                    except pyautogui.FailSafeException:
                        pass
                        
                    self.plocX, self.plocY = self.clocX, self.clocY

                    # 2. INDEX AND THUMB ROTATE (Scroll)
                    # We use the angle between thumb and index to simulate "rotation"
                    angle = math.degrees(math.atan2(index_y - thumb_y, index_x - thumb_x))
                    if angle < -30: # Rotate Right/Up
                        pyautogui.scroll(20)
                    elif angle > 30: # Rotate Left/Down
                        pyautogui.scroll(-20)

                    # 3. INDEX TO THUMB (Drag)
                    dist_drag = self.get_distance(lm_list[4], lm_list[8])
                    if dist_drag < 30:
                        pyautogui.mouseDown()
                    else:
                        pyautogui.mouseUp()

                    # 4. INDEX AND MIDDLE (Right Click)
                    dist_right = self.get_distance(lm_list[8], lm_list[12])
                    if dist_right < 30:
                        pyautogui.rightClick()
                        time.sleep(0.2) # Prevents multiple clicks

                    # 5. INDEX, MIDDLE, AND RING (Left Click)
                    if len(lm_list) > 16:
                        dist_left1 = self.get_distance(lm_list[8], lm_list[12])
                        dist_left2 = self.get_distance(lm_list[12], lm_list[16])
                        if dist_left1 < 30 and dist_left2 < 30:
                            pyautogui.click()
                            time.sleep(0.2)

                    self.mp_draw.draw_landmarks(img, hand_lms, self.mp_hands.HAND_CONNECTIONS)

            cv2.imshow("Hand Tracking Mouse", img)
            # Break cleanly if needed
            if cv2.waitKey(1) & 0xFF == ord('q'):
                self.stop()
                break
        
        self.cap.release()
        cv2.destroyAllWindows()

    def start(self):
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self._run_loop, daemon=True)
            self.thread.start()

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join()
