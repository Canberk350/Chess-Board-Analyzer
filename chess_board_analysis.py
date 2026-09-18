import numpy as np
import threading
import time
import chess
import chess.engine # IMPORT CHESS ENGINE
import cv2
import shutil

# --- 0. CONFIGURATION & STOCKFISH SETUP ---
# Try to find stockfish automatically on Ubuntu, or fallback to default path
STOCKFISH_PATH = shutil.which("stockfish") or "/usr/games/stockfish"

# --- 1. VIDEO STREAM CLASS (Unchanged) ---
class VideoStream:
    def __init__(self, src=0, target_fps=30):
        self.stream = cv2.VideoCapture(src)
        self.stream.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        (self.grabbed, self.frame) = self.stream.read()
        self.stopped = False
        self.lock = threading.Lock()
        self.read_delay = 1.0 / target_fps

    def start(self):
        t = threading.Thread(target=self.update, args=())
        t.daemon = True
        t.start()
        return self

    def update(self):
        while True:
            if self.stopped: return
            time.sleep(self.read_delay) 
            (grabbed, frame) = self.stream.read()
            with self.lock:
                self.grabbed = grabbed
                self.frame = frame

    def read(self):
        with self.lock:
            return self.frame.copy() if self.frame is not None else None

    def stop(self):
        self.stopped = True
        self.stream.release()

# --- 2. SETTINGS ---
url = 0 # "http://192.168.1.127:8080/video" (Changed to 0 for local testing, revert to your URL)
BOARD_SIZE = (7, 7)
IMG_SIZE = 400
SQUARE_SIZE = IMG_SIZE // 8

# Speed Settings
STABILITY_THRESHOLD = 5     
COOLDOWN_DURATION = 2.0     

# Motion Settings
MOTION_THRESHOLD = 25       
HAND_ENTRY_THRESHOLD = 2500 
PAUSE_DURATION = 1.0        

# --- 3. HELPER FUNCTIONS ---
def get_chess_square(row, col):
    file_names = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h']
    rank_names = ['8', '7', '6', '5', '4', '3', '2', '1'] 
    return chess.parse_square(file_names[col] + rank_names[row])

def get_piece_name(piece):
    if piece is None: return ""
    color = "W" if piece.color == chess.WHITE else "B"
    name = {chess.PAWN: "P", chess.KNIGHT: "N", chess.BISHOP: "B",
            chess.ROOK: "R", chess.QUEEN: "Q", chess.KING: "K"}
    return f"{color}{name[piece.piece_type]}"

def nothing(x): pass

# --- 4. VISUAL DEBUGGER ---
def draw_debug_board(frame_state, intensities, logic_board, color_thresh):
    debug_img = np.zeros((400, 400, 3), dtype=np.uint8)
    sq_h = 400 // 8
    sq_w = 400 // 8

    c_white_sq = (240, 217, 181)
    c_black_sq = (181, 136, 99)
    c_ok = (0, 255, 0)      

    for row in range(8):
        for col in range(8):
            x1, y1 = col * sq_w, row * sq_h
            color = c_white_sq if (row + col) % 2 == 0 else c_black_sq
            cv2.rectangle(debug_img, (x1, y1), (x1+sq_w, y1+sq_h), color, -1)

            sq_idx = get_chess_square(row, col)
            logic_piece = logic_board.piece_at(sq_idx)
            is_occupied = frame_state[row][col] == 1
            intensity = intensities[row][col]
            
            seen_color = None 
            if is_occupied:
                seen_color = 'W' if intensity > color_thresh else 'B'

            status_color = (0,0,0)
            thickness = 1
            
            if logic_piece and is_occupied:
                logic_color = 'W' if logic_piece.color == chess.WHITE else 'B'
                if logic_color == seen_color:
                    status_color = c_ok 
                    thickness = 2
                else:
                    status_color = (0, 165, 255) 
                    thickness = 3
            elif not logic_piece and is_occupied:
                status_color = (0, 0, 255)
                thickness = 2
            elif logic_piece and not is_occupied:
                status_color = (0, 255, 255) 
                thickness = 2

            if thickness > 1:
                cv2.rectangle(debug_img, (x1+2, y1+2), (x1+sq_w-2, y1+sq_h-2), status_color, thickness)

            text = ""
            if logic_piece: text = get_piece_name(logic_piece)
            elif is_occupied: text = "?" 

            cv2.putText(debug_img, str(int(intensity)), (x1+2, y1+12), cv2.FONT_HERSHEY_SIMPLEX, 0.3, (0,0,0), 1)

            if text:
                text_size = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2)[0]
                tx = x1 + (sq_w - text_size[0]) // 2
                ty = y1 + (sq_h + text_size[1]) // 2
                txt_c = (255, 255, 255) if 'W' in text else (0, 0, 0)
                outline = (0, 0, 0) if 'W' in text else (255, 255, 255)
                cv2.putText(debug_img, text, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.8, outline, 3)
                cv2.putText(debug_img, text, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.8, txt_c, 1)

    return debug_img

# --- 5. INITIALIZATION ---
print("--- CHESS ROBOT SETUP ---")
color_input = input("What color is the robot playing? (w/b): ").lower()
ROBOT_COLOR = chess.WHITE if color_input == 'w' else chess.BLACK
print(f"Robot playing as: {'WHITE' if ROBOT_COLOR == chess.WHITE else 'BLACK'}")

try:
    engine = chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH)
    print("Stockfish Engine Loaded.")
except Exception as e:
    print(f"Error loading Stockfish: {e}")
    print("Did you install it? Run: sudo apt install stockfish")
    exit()

cap = VideoStream(url, target_fps=30).start()
time.sleep(1.0)

cv2.namedWindow("Settings")
cv2.createTrackbar("Diff Thresh", "Settings", 23, 255, nothing)
cv2.createTrackbar("Min Pixels", "Settings", 150, 1000, nothing)
cv2.createTrackbar("Color Thresh", "Settings", 110, 255, nothing)
cv2.createTrackbar("Contrast", "Settings", 15, 30, nothing) 

calibrated = False      
game_started = False
M = None                
reference_gray = None   
previous_frame_gray = None 
last_corners = None
is_board_detected = False

board_logic = chess.Board()

curr_occupancy = np.zeros((8, 8), dtype=int)
candidate_occupancy = np.zeros((8, 8), dtype=int)
stable_counter = 0

is_paused = False
pause_start_time = 0
in_cooldown = False     

morph_kernel = np.ones((3,3), np.uint8)
pending_promotion_move = None 
game_message = "" 

print("STEP 1: Calibrate (c)")
print("STEP 2: Setup & Start (s)")
print("CONTROLS: 'u' = Update Lighting | 't' = Swap Turn")

try:
    while True:
        frame = cap.read()
        if frame is None: continue

        frame = cv2.resize(frame, (640, 480))
        
        contrast_val = cv2.getTrackbarPos("Contrast", "Settings") / 10.0
        if contrast_val < 1.0: contrast_val = 1.0
        frame = cv2.convertScaleAbs(frame, alpha=contrast_val, beta=0)

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        display_frame = frame.copy()

        PIXEL_DIFF_THRESHOLD = cv2.getTrackbarPos("Diff Thresh", "Settings")
        PIXEL_COUNT_THRESHOLD = cv2.getTrackbarPos("Min Pixels", "Settings")
        COLOR_THRESHOLD = cv2.getTrackbarPos("Color Thresh", "Settings")

        # --- CALIBRATION MODE ---
        if not calibrated:
            cv2.putText(display_frame, "CALIBRATION: Show Empty Board & Press 'c'", (10, 30), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
            if int(time.time()*10)%2 == 0:
                found, corners = cv2.findChessboardCorners(gray, BOARD_SIZE, cv2.CALIB_CB_ADAPTIVE_THRESH + cv2.CALIB_CB_NORMALIZE_IMAGE)
                if found:
                    corners = cv2.cornerSubPix(gray, corners, (11,11), (-1,-1), (cv2.TERM_CRITERIA_EPS+cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001))
                    last_corners = corners
                    cv2.drawChessboardCorners(display_frame, BOARD_SIZE, corners, found)
            elif last_corners is not None:
                 cv2.drawChessboardCorners(display_frame, BOARD_SIZE, last_corners, True)

        # --- GAME MODE ---
        else:
            warped = cv2.warpPerspective(gray, M, (IMG_SIZE, IMG_SIZE))
            warped_blur = cv2.GaussianBlur(warped, (21, 21), 0)

            if previous_frame_gray is None: previous_frame_gray = warped_blur.copy()

            motion_diff = cv2.absdiff(previous_frame_gray, warped_blur)
            _, motion_thresh = cv2.threshold(motion_diff, MOTION_THRESHOLD, 255, cv2.THRESH_BINARY)
            total_motion = cv2.countNonZero(motion_thresh)
            previous_frame_gray = warped_blur.copy()

            # UI INFO
            if not game_started:
                cv2.putText(display_frame, "SETUP: Place Pieces -> Press 's'", (10, 60), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 0, 0), 2)
            else:
                # --- ROBOT LOGIC INSERTION POINT ---
                if board_logic.turn == ROBOT_COLOR and not board_logic.is_game_over() and not pending_promotion_move:
                    print(">>> ROBOT IS THINKING...")
                    cv2.putText(display_frame, "ROBOT THINKING...", (10, 150), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 0, 255), 3)
                    cv2.imshow('Main', display_frame)
                    cv2.waitKey(1) # Force UI update

                    # 1. Ask Stockfish for the best move (Time limit 0.5s)
                    result = engine.play(board_logic, chess.engine.Limit(time=0.5))
                    best_move = result.move
                    print(f">>> ROBOT CALCULATED: {best_move}")

                    # 2. Update Internal Board Logic
                    board_logic.push(best_move)

                    # 3. Trigger Cooldown to allow robot execution time
                    # This gives the robot time to physically move before the camera starts judging
                    is_paused = True
                    pause_start_time = time.time()
                    in_cooldown = True 
                    
                    # Note: At this point, the Internal Logic has moved, but the Physical Camera
                    # still sees the old board. The 'Visual Debugger' will show errors (Yellow/Red boxes)
                    # until the physical robot arm completes the move.

                # --- END ROBOT LOGIC ---

                turn_text = "Turn: WHITE" if board_logic.turn == chess.WHITE else "Turn: BLACK"
                color = (255, 255, 255) if board_logic.turn == chess.WHITE else (0, 0, 0)
                cv2.putText(display_frame, turn_text, (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
                
                if game_message:
                    cv2.putText(display_frame, game_message, (10, 100), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 3)

                if pending_promotion_move:
                     cv2.putText(display_frame, "PROMOTE: Press q, r, b, or n", (50, 240), 
                                 cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 255), 3)

            # ... [Rest of your existing Pause/Motion Logic] ...
            if is_paused:
                elapsed = time.time() - pause_start_time
                if elapsed < PAUSE_DURATION:
                    remaining = int(PAUSE_DURATION - elapsed) + 1
                    cv2.putText(display_frame, f"WAITING: {remaining}s", (50, 240), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0,0,255), 3)
                    key = cv2.waitKey(1) & 0xFF
                    if key == ord('q'): break
                    cv2.imshow('Main', display_frame) 
                    continue
                else:
                    if not in_cooldown:
                        in_cooldown = True
                        pause_start_time = time.time() 
                    
                    cooldown_elapsed = time.time() - pause_start_time
                    if cooldown_elapsed < COOLDOWN_DURATION:
                          cv2.putText(display_frame, f"SETTLING: {int(COOLDOWN_DURATION - cooldown_elapsed) + 1}s", (50, 240), 
                                      cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 255), 3)
                          cv2.imshow('Main', display_frame)
                          if cv2.waitKey(1) & 0xFF == ord('q'): break
                          continue
                    else:
                        is_paused = False
                        in_cooldown = False
                        stable_counter = 0 
                        print("RESUMING BOARD READ")

            if total_motion > HAND_ENTRY_THRESHOLD and game_started:
                is_paused = True
                in_cooldown = False 
                pause_start_time = time.time()
                continue

            diff = cv2.absdiff(reference_gray, warped_blur)
            _, thresh = cv2.threshold(diff, PIXEL_DIFF_THRESHOLD, 255, cv2.THRESH_BINARY)
            thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, morph_kernel) 
            
            temp_occupancy = np.zeros((8,8), dtype=int)
            temp_intensity = np.zeros((8,8), dtype=float)
            temp_pixel_counts = np.zeros((8,8), dtype=int)

            MARGIN = int(SQUARE_SIZE * 0.25)
            for r in range(8):
                for c in range(8):
                    x1, y1 = c*SQUARE_SIZE, r*SQUARE_SIZE
                    roi = warped[y1+MARGIN:y1+SQUARE_SIZE-MARGIN, x1+MARGIN:x1+SQUARE_SIZE-MARGIN]
                    mask = thresh[y1+MARGIN:y1+SQUARE_SIZE-MARGIN, x1+MARGIN:x1+SQUARE_SIZE-MARGIN]
                    
                    px_count = cv2.countNonZero(mask)
                    temp_pixel_counts[r][c] = px_count

                    if px_count > PIXEL_COUNT_THRESHOLD:
                        temp_occupancy[r][c] = 1
                        temp_intensity[r][c] = np.mean(roi)

            if np.array_equal(temp_occupancy, candidate_occupancy):
                stable_counter += 1
            else:
                candidate_occupancy = temp_occupancy.copy()
                stable_counter = 0
            
            if stable_counter < STABILITY_THRESHOLD:
                 cv2.putText(display_frame, "Stabilizing...", (10, 450), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
            else:
                 cv2.putText(display_frame, "Stable", (10, 450), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

            # ==========================================================
            #  HUMAN MOVE DETECTION LOGIC
            # ==========================================================
            if stable_counter == STABILITY_THRESHOLD: 
                curr_occupancy = candidate_occupancy.copy()
                curr_intensity = temp_intensity.copy()
                
                debug_view = draw_debug_board(curr_occupancy, curr_intensity, board_logic, COLOR_THRESHOLD)
                cv2.imshow("Logic Debug", debug_view)

                # ONLY run visual detection if it is NOT the robot's turn
                if game_started and not pending_promotion_move and not board_logic.is_game_over() and board_logic.turn != ROBOT_COLOR:
                    possible_moves = []
                    attacker_color = board_logic.turn
                    
                    for move in board_logic.legal_moves:
                        src_sq = move.from_square
                        dst_sq = move.to_square
                        
                        r_src, c_src = 7 - chess.square_rank(src_sq), chess.square_file(src_sq)
                        r_dst, c_dst = 7 - chess.square_rank(dst_sq), chess.square_file(dst_sq)

                        # 1. Occupancy Check
                        cam_src_empty = (curr_occupancy[r_src][c_src] == 0)
                        cam_dst_full = (curr_occupancy[r_dst][c_dst] == 1)
                        if not (cam_src_empty and cam_dst_full): continue

                        # 2. Color Verification
                        dest_intensity = curr_intensity[r_dst][c_dst]
                        looks_white = dest_intensity > COLOR_THRESHOLD
                        if attacker_color == chess.WHITE and not looks_white: continue 
                        if attacker_color == chess.BLACK and looks_white: continue 

                        # 3. Castling Check
                        if board_logic.is_castling(move):
                            is_kingside = (chess.square_file(dst_sq) > chess.square_file(src_sq))
                            rank = chess.square_rank(src_sq) 
                            if is_kingside: 
                                rook_src, rook_dst = chess.square(7, rank), chess.square(5, rank) 
                            else: 
                                rook_src, rook_dst = chess.square(0, rank), chess.square(3, rank) 

                            r_rsrc, c_rsrc = 7 - chess.square_rank(rook_src), chess.square_file(rook_src)
                            r_rdst, c_rdst = 7 - chess.square_rank(rook_dst), chess.square_file(rook_dst)
                            
                            cam_rook_src_empty = (curr_occupancy[r_rsrc][c_rsrc] == 0)
                            cam_rook_dst_full = (curr_occupancy[r_rdst][c_rdst] == 1)
                            if not (cam_rook_src_empty and cam_rook_dst_full): continue

                        score = temp_pixel_counts[r_dst][c_dst]
                        possible_moves.append((move, score))

                    # --- EXECUTION ---
                    if len(possible_moves) > 0:
                        possible_moves.sort(key=lambda x: x[1], reverse=True)
                        best_move, score = possible_moves[0]
                        
                        if best_move.promotion: 
                            print("PROMOTION DETECTED! Waiting for user input...")
                            pending_promotion_move = best_move 
                            is_paused = True 
                            in_cooldown = False 
                        else:
                            print(f"HUMAN MOVED: {best_move}")
                            if board_logic.is_castling(best_move): print(">>> CASTLING EXECUTED <<<")
                            
                            board_logic.push(best_move)
                            
                            if board_logic.is_checkmate():
                                game_message = "CHECKMATE!"
                                print("GAME OVER: CHECKMATE")
                            elif board_logic.is_check():
                                game_message = "CHECK!"
                                print("CHECK!")
                            elif board_logic.is_stalemate():
                                game_message = "STALEMATE"
                            else:
                                game_message = "" 
                                
                            is_paused = True
                            pause_start_time = time.time()
                            in_cooldown = True 
                            
            cv2.imshow("Analysis", thresh) 

        cv2.imshow('Main', display_frame) 

        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'): break
        elif key == ord('u'):
            warped_ref = cv2.warpPerspective(gray, M, (IMG_SIZE, IMG_SIZE))
            reference_gray = cv2.GaussianBlur(warped_ref, (21, 21), 0)
            print("REF UPDATED")
        elif key == ord('t') and game_started:
            board_logic.turn = not board_logic.turn
            print("TURN SWAP")
        elif key == ord('c') and not calibrated:
            if last_corners is not None:
                c = last_corners
                src = np.float32([c[0][0], c[6][0], c[42][0], c[48][0]])
                dst = np.float32([[SQUARE_SIZE, SQUARE_SIZE], [IMG_SIZE-SQUARE_SIZE, SQUARE_SIZE], 
                                  [SQUARE_SIZE, IMG_SIZE-SQUARE_SIZE], [IMG_SIZE-SQUARE_SIZE, IMG_SIZE-SQUARE_SIZE]])
                M = cv2.getPerspectiveTransform(src, dst)
                warped_ref = cv2.warpPerspective(gray, M, (IMG_SIZE, IMG_SIZE))
                reference_gray = cv2.GaussianBlur(warped_ref, (21, 21), 0)
                calibrated = True
        elif key == ord('s') and calibrated:
            game_started = True
            board_logic = chess.Board()
            game_message = ""
        elif key == ord('r'):
            game_started = False

except KeyboardInterrupt: