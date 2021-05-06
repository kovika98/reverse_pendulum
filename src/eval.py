from DCPEnv import DCPEnv
from models import CNNModel

def main():
    env = DCPEnv()
    model = CNNModel(num_actions=env.action_space.n)
    model.load_weights(f'saves/{model.label}').expect_partial()
    for i in range(4):
        print("Alive for %.1f seconds" % (env.test(model, True) / 10.0))
    env.close()

if __name__ == "__main__":
    main()