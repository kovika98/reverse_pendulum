import gym
import dataclasses
from dataclasses import dataclass, astuple
import numpy as np
from CarRenderer import CarRenderer
import imageio
import collections


class DCPEnv(gym.Env):

    # Boundaries
    carDist = 4
    maxG = 1
    maxT = 0.94

    # Cart data - !!! MODIFICATIONS HERE !!!
    car_width = 2
    lenP = 2.4
    radW = 0.2

    # Universal constants
    g = 9.81
    coefR = 0.001
    dt = 0.1

    # Computed values
    mC = car_width + 2 * (radW ** 2) * np.pi
    mP = lenP * 0.2
    p_I = 1/3 * mP * (lenP ** 2)
    mTot = mC + mP
    maxX = 6

    @dataclass()
    class State:
        p_G: float = 0.0
        p_dG: float = 0.0
        c_X: float = 0.0
        c_dX: float = 0.0

        def flatten(self):
            return (self.p_G, self.p_dG, self.c_X, self.c_dX)

        def wind_blow(self, torque):
            self.p_dG += torque / DCPEnv.p_I * DCPEnv.dt

        def noise(self):
            noise = np.random.standard_normal(4)
            scale = (.1, .01, .4, .1)
            self.p_G, self.p_dG, self.c_X, self.c_dX = (
                x + s * n for x, s, n in zip(self.flatten(), scale, noise))
            return self

        def add_force(self, F):
            sinG = np.sin(self.p_G)
            cosG = np.cos(self.p_G)

            _a = (-1 * F - DCPEnv.mP * 0.5 * DCPEnv.lenP * (self.p_dG ** 2) *
                  sinG) / DCPEnv.mTot
            _b = (4/3 - DCPEnv.mP * (cosG ** 2) / DCPEnv.mTot)

            p_ddG = (DCPEnv.g * sinG + cosG * _a) / (0.5 * DCPEnv.lenP * _b)

            _c = (self.p_dG ** 2) * sinG - \
                p_ddG * cosG
            c_ddX = (F + DCPEnv.mP * 0.5 * DCPEnv.lenP * _c) / DCPEnv.mTot

            self.c_dX += DCPEnv.dt * c_ddX
            self.c_X += DCPEnv.dt * self.c_dX
            self.p_dG += DCPEnv.dt * p_ddG
            self.p_G += DCPEnv.dt * self.p_dG

    actions_size = 7

    def __init__(self, num_cars=1, time_step=0.1, buffer_size=1):
        DCPEnv.maxX = (1 + num_cars) / 2 * DCPEnv.carDist
        self.observations_size = len(
            dataclasses.fields(DCPEnv.State)) * num_cars
        DCPEnv.dt = time_step
        self.viewer = None
        self.render_data = {"wW": self.maxX * 2, "pW": self.mP / self.lenP,
                            "pL": self.lenP, "cW": self.car_width, "wR": self.radW}
        self.num_cars = num_cars
        self.buffer_size = buffer_size

    def _register_observation(self, observation):
        self.buffer = np.roll(self.buffer, -1, axis=0)
        self.buffer[-1] = observation
        return self.buffer

    def _init_renderer(self):
        viewer = CarRenderer(data_dict=self.render_data)
        for _ in range(self.num_cars):
            viewer.add_car()
        return viewer

    def _convert_states(self):
        return np.array(sum((astuple(s) for s in self.states), tuple()))

    def _collision_detect(self, left, right):
        if abs(left.c_X - right.c_X) < DCPEnv.car_width:
            push = (DCPEnv.car_width - abs(left.c_X - right.c_X)) / 2
            left.c_X -= push
            right.c_X += push

            mom = [left.c_dX * DCPEnv.mC, right.c_dX * DCPEnv.mC]
            mom_switch = tuple([0.98 * m for m in reversed(mom)])

            F = [(m2-m1) / DCPEnv.dt for m1, m2 in zip(mom, mom_switch)]
            left.add_force(F[0])
            right.add_force(F[1])

    # ==================================================
    # =================== STEP =========================
    def step(self, actions):
        terminates = [False] * self.num_cars
        for state, action, i in zip(self.states, actions, range(self.num_cars)):
            torque = np.linspace(-self.maxT, self.maxT,
                                 DCPEnv.actions_size)[action]

            if np.random.random() < 1e-4:
                t = np.random.standard_normal() * 0.2
                state.wind_blow(np.random.choice([-t, t]))
            F = (2.0*torque - DCPEnv.coefR *
                 DCPEnv.mTot * DCPEnv.g/2.0)/DCPEnv.radW
            state.add_force(F)

            if abs(state.p_G) > self.maxG or abs(state.c_X) > self.maxX:
                terminates[i] = True
        for i in range(len(self.states) - 1):
            self._collision_detect(self.states[i], self.states[i+1])

        next_state = np.array(self._convert_states())
        return self._register_observation(next_state), np.ones(self.num_cars), terminates

    # ==================================================
    # =================== RESET ========================
    # ========== initialize cars here ==================
    def reset(self):
        self.states = [DCPEnv.State(
            c_X=DCPEnv.carDist*(1-self.num_cars+2*i)/2).noise()
            for i in range(self.num_cars)]
        state = self._convert_states()
        self.buffer = np.array([state for _ in range(self.buffer_size)])
        return self.buffer

    def test(self, models, render=True, gif_path=None, max_seconds = 600, fps=10):
        if not isinstance(models, (collections.Sequence, np.ndarray)):
            models = np.array([models])
        model_num = len(models)
        obs_window, deaths = self.reset(), [False] * model_num
        frames = []
        actions = np.empty(model_num, dtype=np.int32)
        steps = 0
        dt = 0
        while not any(deaths):
            for m_i, model in enumerate(models):
                actions[m_i], _ = model.action_value(obs_window)
            obs_window, _, deaths = self.step(actions)
            steps += 1
            dt += DCPEnv.dt
            if dt+1e-4 > 1./fps:
                dt = 0
                if gif_path is not None:
                    frames.append(self.render(mode='rgb_array'))
                if render:
                    self.render(mode='human')
            if steps*DCPEnv.dt >= max_seconds:
                break
        if len(frames) > 0:
            imageio.mimsave(gif_path, frames, fps=fps)
        death_list = {}
        for model, dead in zip(models, deaths):
            death_list[model.label] = dead
        return steps*DCPEnv.dt, death_list

    def render(self, mode):
        if self.viewer is None:
            self.viewer = self._init_renderer()

        if self.states is None:
            return None

        return self.viewer.render_cars(self.states, mode)

    def close(self):
        if self.viewer:
            self.viewer.close()
            self.viewer = None


def preview():
    env = DCPEnv(num_cars=4)
    print(env.reset())
    env.render('human')
    input("")
    env.close()


if __name__ == "__main__":
    preview()
