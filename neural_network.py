import tensorflow as tf
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import Dense, Dropout
import numpy as np

class SCALNeuralNetwork:
    """
    TensorFlow/Keras model to predict missing Relative Permeability curves.
    """
    def __init__(self):
        self.model = self._build_model()

    def _build_model(self):
        # Standard MLP Architecture for SCAL Regression
        # Inputs: [Porosity, Permeability, Swi, Sor]
        model = Sequential([
            Dense(32, input_dim=4, activation='relu', name='hidden_layer_1'),
            Dense(16, activation='relu', name='hidden_layer_2'),
            Dropout(0.1, name='regularization_dropout'),
            Dense(1, activation='linear', name='output_krw')
        ])
        
        # Compile utilizing Adam optimizer and Mean Squared Error loss
        model.compile(optimizer='adam', loss='mse', metrics=['mae'])
        return model

    def train(self, X_train, y_train, epochs=100):
        # Trains the model silently on historical core data
        self.model.fit(X_train, y_train, epochs=epochs, verbose=0)

    def predict_endpoint(self, data_dict):
        """
        Predicts relative permeability endpoints (e.g., krw @ Sor) based on extracted core data.
        """
        x_input = np.array([[
            data_dict['Porosity'],
            data_dict['Permeability'],
            data_dict['Swi'],
            data_dict['Sor']
        ]])
        
        prediction = self.model.predict(x_input, verbose=0)
        return float(prediction[0][0])
