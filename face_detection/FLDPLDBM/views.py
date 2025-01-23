from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from .forms import SignupForm
from neo4j import GraphDatabase, Neo4jDriver
import numpy as np
import cv2
import json
import ast
from collections import defaultdict  # Add this line
import numpy as np
from keras_facenet import FaceNet
from django.http import JsonResponse, HttpResponse
from datetime import datetime, timezone
import threading
from django.views import View
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from sklearn.metrics.pairwise import cosine_similarity
from django.urls import path
import numpy as np
import json
from sklearn.metrics.pairwise import cosine_similarity

NEO4J_URI = 'neo4j+s://9094f4bc.databases.neo4j.io'
NEO4J_USER = 'neo4j'
NEO4J_PASSWORD = 'djWulnOU1qIkc5j_64OUnlI7h6EJjoOQjJ5O_0IbbmE'

# Initialize FaceNet model
embedder = FaceNet()

class Neo4jHandler:
    def __init__(self, uri, user, password):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self):
        self.driver.close()

    def create_user_node(self, username):
        with self.driver.session() as session:
            session.run("CREATE (p:Person {id: $username})", username=username)

    def create_image_node(self, username, embedding):
        created_at = datetime.now(timezone.utc).isoformat()
        embedding_flatten = embedding.flatten().tolist()  # Convert to JSON string
        with self.driver.session() as session:
            session.run(
                """
                MATCH (p:Person {id: $username})
                CREATE (img:Image {id: $username, embedding: $embedding, created_at: $created_at})
                CREATE (p)-[:HAS_IMAGE]->(img)
                """,
                username=username,
                embedding=embedding_flatten,
                created_at=created_at
            )


    def find_similar_person(self, new_embedding):
        with self.driver.session() as session:
            result = session.run("""
                MATCH (p:Person)-[:HAS_IMAGE]->(img:Image)
                RETURN p.id AS person_id, img.embedding AS embeddings
            """)
            
            # Group embeddings by person using defaultdict
            person_embeddings = defaultdict(list)  # Now works!
            for record in result:
                person_id = record["person_id"]
                embedding = np.array(record["embeddings"])
                person_embeddings[person_id].append(embedding)
        
        # Rest of your code...
            
            # Average embeddings per person in Python
            avg_embeddings = []
            for person_id, embeddings in person_embeddings.items():
                avg_embedding = np.mean(embeddings, axis=0)
                avg_embeddings.append((person_id, avg_embedding))
            
            # Calculate similarities
            similarities = [
                (person_id, cosine_similarity([new_embedding], [avg_embedding])[0][0])
                for person_id, avg_embedding in avg_embeddings
            ]
            return sorted(similarities, key=lambda x: x[1], reverse=True)[:3]
    
    def get_user_embeddings(self, username):
        try:
            query = """
                MATCH (p:Person {id: $username})-[:HAS_IMAGE]->(img:Image)
                RETURN img.embedding AS embedding, img.created_at AS created_at
            """
            with self.driver.session() as session:
                result = session.run(query, username=username)
                records = list(result)  # Convert to list to prevent consumption
                
            return [
                {"embedding": record["embedding"], "created_at": record["created_at"]}
                for record in records
            ]
        except Exception as e:
            print(f"Error in get_user_embeddings: {e}")
            return []

def signup_view(request):
    if request.method == 'POST':
        form = SignupForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            # Hash the password
            user.set_password(form.cleaned_data['password'])
            user.save()
            # Create a Neo4j node for the new user
            neo4j_handler = Neo4jHandler(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD)
            try:
                neo4j_handler.create_user_node(user.username)
            finally:
                neo4j_handler.close()
            # Redirect to a success page or login page
            return HttpResponse("Successfully Signed Up!") and redirect('login')
    else:
        form = SignupForm()

    return render(request, 'signup.html', {'form': form})


def loginPage(request):
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            username = form.cleaned_data['username']
            password = form.cleaned_data['password']
            user = authenticate(request, username=username, password=password)
            if user is not None:
                login(request, user)
                return redirect('landing')  # Redirect to your landing page
            else:
                return HttpResponse("Username or Password is incorrect!")
    else:
        form = AuthenticationForm()

    return render(request, 'login.html', {'form': form})


def logoutPage(request):
    logout(request)
    return redirect('login')

# Helper Function to Process Image and Generate Embedding


def process_image_and_get_embedding(image_data):
    # Removed normalization to match Code 1/2
    np_arr = np.frombuffer(image_data, np.uint8)
    img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    img_resized = cv2.resize(img, (160, 160))
    img_array = np.expand_dims(img_resized, axis=0)  # No division by 255
    return embedder.embeddings(img_array)[0]


@login_required
def landingPage(request):
    neo4j_handler = Neo4jHandler(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD)
    try:
        # Get embeddings for the logged-in user
        embeddings_data = neo4j_handler.get_user_embeddings(
            request.user.username)
        # Count the number of embeddings
        num_embeddings = len(embeddings_data)
        # Extract creation dates
        embedding_info = [
            {"embedding_id": idx + 1, "created_at": record["created_at"]}
            for idx, record in enumerate(embeddings_data)
        ]
    finally:
        neo4j_handler.close()
    # Prepare context data
    context = {
        "username": request.user.username,
        "num_embeddings": num_embeddings,
        "embedding_info": embedding_info,
        "max_embeddings": 5,  # Define the maximum allowed embeddings
    }
    if request.method == 'POST':
        try:
            # Handle the image sent as a Blob
            image_file = request.FILES.get('image')
            if not image_file:
                return HttpResponse("No image file received.", status=400)
            # Read the image data
            image_bytes = image_file.read()
            '''# Save the raw image data into a txt file
            with open('image_data_2.txt', 'wb') as f:
                f.write(image_bytes)'''
            # Process the image and get embedding
            embedding = process_image_and_get_embedding(image_bytes)
            '''# save the embedding into a txt file
            with open('embedding_data_2.txt', 'wb') as f:
                f.write(embedding.tobytes())'''
            # Save embedding to Neo4j
            neo4j_handler = Neo4jHandler(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD)
            try:
                print("Trying to store embedding in Neo4j")
                neo4j_handler.create_image_node(
                    request.user.username, embedding)
                print("Embedding stored in Neo4j")
            finally:
                neo4j_handler.close()
                print("Neo4j connection closed")
            return JsonResponse({"message": "Image processed and embedding stored successfully!"})
        except Exception as e:
            return JsonResponse({"error": f"Error processing image: {e}"}, status=500)
    return render(request, 'landing.html', context)


@login_required
def delete_embedding(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            # This is for frontend display purposes
            embedding_id = data.get('embedding_id')
            # This is used for identifying the embedding to delete
            created_at = data.get('created_at')
            if not created_at:
                return JsonResponse({"error": "created_at is required."}, status=400)
            # Connect to Neo4j and delete the embedding based on the created_at timestamp
            neo4j_handler = Neo4jHandler(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD)
            try:
                with neo4j_handler.driver.session() as session:
                    result = session.run(
                        """
                        MATCH (p:Person {id: $username})-[:HAS_IMAGE]->(img:Image {created_at: $created_at})
                        DETACH DELETE img
                        RETURN COUNT(img) AS deletedCount
                        """,
                        username=request.user.username,
                        created_at=created_at
                    )
                    deleted_count = result.single()["deletedCount"]
                    if deleted_count == 0:
                        return JsonResponse({"error": "No matching embedding found to delete."}, status=404)
            finally:
                neo4j_handler.close()
            return JsonResponse({"message": "Embedding deleted successfully."})
        except Exception as e:
            return JsonResponse({"error": f"Error deleting embedding: {e}"}, status=500)
    return JsonResponse({"error": "Invalid request method."}, status=400)

#Added by Samuel


class FaceRecognitionAPI(View):
    camera_thread = None
    stop_event = threading.Event()
    recognized_persons = []
    lock = threading.Lock()
    face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')

    @method_decorator(csrf_exempt)
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)

    @classmethod
    def start_camera(cls):
        cls.stop_event.clear()
        cap = cv2.VideoCapture(0)
        neo4j_handler = Neo4jHandler(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD)

        while not cls.stop_event.is_set():
            ret, frame = cap.read()
            if not ret:
                continue

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = cls.face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))

            current_frame_recognitions = []
            for (x, y, w, h) in faces:
                # Face processing
                face = frame[y:y+h, x:x+w]
                face = cv2.resize(face, (160, 160))
                face_array = np.expand_dims(face, axis=0)
                new_embedding = embedder.embeddings(face_array)[0]

                # Get similarities
                similar_persons = neo4j_handler.find_similar_person(new_embedding)
                
                # Determine if top 3 belong to the same person
                if len(similar_persons) >= 1:
                    main_person, max_similarity = similar_persons[0]
                    if all(person == main_person for person, _ in similar_persons[:3]):
                        # Draw green box and name for confirmed match
                        cv2.rectangle(frame, (x, y), (x+w, y+h), (0, 255, 0), 2)
                        cv2.putText(frame, f"{main_person} ({max_similarity:.2f})", 
                                   (x, y-10), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0,255,0), 2)
                    else:
                        # Draw yellow box for uncertain matches
                        cv2.rectangle(frame, (x, y), (x+w, y+h), (0, 255, 255), 2)

                current_frame_recognitions.extend(similar_persons)

            # Thread-safe update
            with cls.lock:
                cls.recognized_persons = current_frame_recognitions

            # Show live preview window
            cv2.imshow("Face Recognition - Press Q to quit", frame)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

        cap.release()
        cv2.destroyAllWindows()
        neo4j_handler.close()

    @classmethod
    def stop_camera(cls):
        cls.stop_event.set()
        if cls.camera_thread and cls.camera_thread.is_alive():
            cls.camera_thread.join(timeout=2)
            cls.camera_thread = None

    def post(self, request, action):
        if action == "start":
            if self.camera_thread and self.camera_thread.is_alive():
                return JsonResponse({"error": "Already running"}, status=400)
                
            self.camera_thread = threading.Thread(target=self.start_camera)
            self.camera_thread.daemon = True  # Allow server to exit cleanly
            self.camera_thread.start()
            return JsonResponse({"message": "Camera started"})

        elif action == "stop":
            self.stop_camera()
            with self.lock:
                results = self.recognized_persons.copy()
            return JsonResponse({"recognized": results})

        return JsonResponse({"error": "Invalid action"}, status=400)