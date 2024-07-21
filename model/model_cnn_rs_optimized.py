import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score
from sklearn.model_selection import ParameterGrid
import tensorflow as tf
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import Conv3D, Flatten, Dense, MaxPooling3D, GlobalAveragePooling3D, GlobalMaxPooling3D
from tensorflow.keras.optimizers import Adam
from tensorflow.keras import backend as K
from tensorflow.keras.callbacks import Callback
from argparse import ArgumentParser

PROGRAM_NAME = "model_cnn_rs_optimized.py"

def f1_m(y_true, y_pred):
    y_pred = K.round(y_pred)
    tp = K.sum(K.cast(y_true * y_pred, 'float'), axis=0)
    fp = K.sum(K.cast((1 - y_true) * y_pred, 'float'), axis=0)
    fn = K.sum(K.cast(y_true * (1 - y_pred), 'float'), axis=0)

    precision = tp / (tp + fp + K.epsilon())
    recall = tp / (tp + fn + K.epsilon())

    # Check for NaNs and set them to 0
    precision = tf.where(tf.math.is_nan(precision), K.zeros_like(precision), precision)
    recall = tf.where(tf.math.is_nan(recall), K.zeros_like(recall), recall)

    f1 = 2 * (precision * recall) / (precision + recall + K.epsilon())
    f1 = tf.where(tf.math.is_nan(f1), K.zeros_like(f1), f1)  # Ensure f1 is zero where it should be

    return K.mean(f1)

def build_cnn_model(input_shape, pooling_type='flatten', num_hidden_layers=1, nodes_per_layer=128):
    model = Sequential([
        Conv3D(32, kernel_size=(3, 3, 3), activation='relu', input_shape=input_shape),
        MaxPooling3D(pool_size=(2, 2, 2), padding='same'),
        Conv3D(64, kernel_size=(3, 3, 3), activation='relu'),
        MaxPooling3D(pool_size=(2, 2, 2), padding='same')
    ])
    
    if pooling_type == 'flatten':
        model.add(Flatten())
    elif pooling_type == 'global_avg':
        model.add(GlobalAveragePooling3D())
    elif pooling_type == 'global_max':
        model.add(GlobalMaxPooling3D())
    
    for _ in range(num_hidden_layers):
        model.add(Dense(nodes_per_layer, activation='relu'))
    
    model.add(Dense(1, activation='sigmoid'))
    model.compile(optimizer=Adam(), loss='binary_crossentropy', metrics=['accuracy', tf.keras.metrics.Recall(), f1_m])
    return model

class MetricsCallback(Callback):
    def __init__(self, X_test, y_test):
        super().__init__()
        self.X_test = X_test
        self.y_test = y_test

    def on_epoch_end(self, epoch, logs=None):
        y_pred = self.model.predict(self.X_test)
        y_pred_classes = np.where(y_pred > 0.5, 1, 0)

        accuracy = accuracy_score(self.y_test, y_pred_classes)
        precision = precision_score(self.y_test, y_pred_classes, average='weighted', zero_division=0)
        recall = recall_score(self.y_test, y_pred_classes, average='weighted', zero_division=0)
        f1 = f1_score(self.y_test, y_pred_classes, average='weighted', zero_division=0)

        print(PROGRAM_NAME)
        print(f"Epoch {epoch + 1}")
        print(f"Accuracy: {accuracy}")
        print(f"Precision: {precision}")
        print(f"Recall: {recall}")
        print(f"F1 Score: {f1}")

def process_and_evaluate_model(filename, test_size, input_shape, pooling_type, num_hidden_layers, nodes_per_layer, epochs):
    # Load dataset
    dataset = pd.read_csv(filename)

    # Filter dataset for molecules with exactly one chiral center
    dataset = dataset[dataset['chiral_length'] == 1]

    # Ensure tensor data has 729 values
    def parse_tensor(tensor_str):
        values = np.fromstring(tensor_str, sep=' ')
        assert len(values) == 729, f"Tensor does not have 729 values: {len(values)}"
        return values.reshape(9, 9, 9)

    # Convert tensor data
    tensor_data = np.stack(dataset['tensor'].apply(parse_tensor).values)
    tensor_data = tensor_data[..., np.newaxis]  # Add a channel dimension for CNN

    # Labels
    labels = dataset['chiral0'].apply(lambda x: 1 if x == 'R' else 0).values

    # Split data
    X_train, X_test, y_train, y_test = train_test_split(tensor_data, labels, test_size=test_size, random_state=42)

    # Train the CNN model
    model = build_cnn_model(input_shape, pooling_type, num_hidden_layers, nodes_per_layer)
    metrics_callback = MetricsCallback(X_test, y_test)
    model.fit(X_train, y_train, epochs=epochs, batch_size=32, verbose=1, callbacks=[metrics_callback], validation_data=(X_test, y_test))

    # Predict and evaluate
    y_pred = model.predict(X_test)
    y_pred_classes = np.where(y_pred > 0.5, 1, 0)

    # Calculate metrics
    accuracy = accuracy_score(y_test, y_pred_classes)
    precision = precision_score(y_test, y_pred_classes, average='weighted', zero_division=0)
    recall = recall_score(y_test, y_pred_classes, average='weighted', zero_division=0)
    f1 = f1_score(y_test, y_pred_classes, average='weighted', zero_division=0)

    return len(dataset), accuracy, precision, recall, f1

def grid_search(filename, test_size, input_shape, param_grid):
    best_score = 0
    best_params = None
    best_result = None
    
    for params in ParameterGrid(param_grid):
        print(f"{PROGRAM_NAME} Testing with parameters: {params}")
        length, accuracy, precision, recall, f1 = process_and_evaluate_model(
            filename,
            test_size,
            input_shape,
            params['pooling_type'],
            params['num_hidden_layers'],
            params['nodes_per_layer'],
            params['epochs']
        )
        
        score = (accuracy + precision + recall + f1) / 4
        if score > best_score:
            best_score = score
            best_params = params
            best_result = {
                "Length of Filtered Dataset": length,
                "Accuracy": accuracy,
                "Precision": precision,
                "Recall": recall,
                "F1 Score": f1
            }
    
    print(f"{PROGRAM_NAME} Best parameters: {best_params}")
    return best_result

def main():
    parser = ArgumentParser()
    parser.add_argument("filename", help="The filename of the dataset")
    parser.add_argument("test_size", type=float, help="The test size for the train-test split")
    args = parser.parse_args()

    filename = args.filename
    test_size = args.test_size
    input_shape = (9, 9, 9, 1)  # Assuming the tensor is 9x9x9 with a single channel

    param_grid = {
        'pooling_type': ['flatten'],
        'num_hidden_layers': [4],
        'nodes_per_layer': [128],
        'epochs': [50]
    }

    best_result = grid_search(filename, test_size, input_shape, param_grid)
    results_df = pd.DataFrame([best_result])
    results_df.to_csv(f"{PROGRAM_NAME}_results.csv", index=False)

if __name__ == "__main__":
    main()