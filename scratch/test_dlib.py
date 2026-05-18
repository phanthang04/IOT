import dlib
print(f"dlib version: {dlib.__version__}")
detector = dlib.get_frontal_face_detector()
print("dlib detector created successfully!")
