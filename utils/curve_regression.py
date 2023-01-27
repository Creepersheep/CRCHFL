import matplotlib.pyplot as plt
from scipy.optimize import curve_fit

epoch =[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40]
cloud_loss = [1.853258729, 1.76964581, 1.784315228, 1.750964761, 1.567705035, 1.654166698, 1.470093489, 1.3362602, 1.28441143, 1.349730849, 1.150846362, 1.061595082, 1.130332232, 1.033548355, 1.057714343, 0.995010316, 1.06848228, 0.930660307, 0.908592582, 0.866158068, 0.84840703, 0.844695747, 0.832722008, 0.832242072, 0.842059791, 0.814491153, 0.814535797, 0.8365345, 0.827394605, 0.800399959, 0.794475377, 0.795884371, 0.797051728, 0.750152826, 0.75721699, 0.764646113, 0.76763773, 0.75791198, 0.751613081, 0.756779253]
edge0_loss = [ 1.794057131, 1.743020654, 1.756538272, 1.677761674, 1.628086925, 1.655025601, 1.541066051, 1.434572935, 1.45027113, 1.29672277, 1.322214007, 1.26184082, 1.309335828, 1.155807376, 1.114306688, 1.222040892, 1.315410852, 1.072485447, 1.072719812, 0.9477458, 0.909539759, 0.954615772, 0.894791543, 0.901453257, 0.922948062, 0.874135613, 0.893645108, 0.909816265, 0.941594243, 0.875557363, 0.892509639, 0.87360543, 0.897691965, 0.806818724, 0.820377409, 0.85652405, 0.897627175, 0.849326849, 0.816509843, 0.785094082]
edge1_loss = [ 1.758653045, 1.692086458, 1.554355025, 1.559522629, 1.430340052, 1.342512488, 1.32569623, 1.286630273, 1.272769094, 1.416827083, 1.024114132, 0.983187914, 1.092924953, 1.057654023, 1.076754689, 0.95206064, 0.929333031, 0.941564202, 0.912532389, 0.863006592, 0.84963733, 0.839912474, 0.837869346, 0.846607029, 0.847882152, 0.816266894, 0.810821712, 0.810261309, 0.805564225, 0.817101836, 0.786654294, 0.783154249, 0.78016603, 0.750540674, 0.757396936, 0.776990116, 0.74918282, 0.772595286, 0.775447905, 0.759838581]

def curve(x, a, b):
    return a * x ** (-b)

def main():
    plt.plot(epoch, cloud_loss, 'b-', label='cloud data')
    plt.plot(epoch, edge0_loss, 'k-', label='edge0 data')
    plt.plot(epoch, edge1_loss, 'g-', label='edge1 data')

    popt, pcov = curve_fit(curve, epoch, cloud_loss)
    plt.plot(epoch, curve(epoch, *popt), 'r-',
         label='cloud fit: a=%5.3f, b=%5.3f' % tuple(popt))

    popt, pcov = curve_fit(curve, epoch, edge0_loss)
    plt.plot(epoch, curve(epoch, *popt), 'y-',
         label='edge0 fit: a=%5.3f, b=%5.3f' % tuple(popt))

    popt, pcov = curve_fit(curve, epoch, edge1_loss)
    plt.plot(epoch, curve(epoch, *popt), 'c-',
         label='edge1 fit: a=%5.3f, b=%5.3f' % tuple(popt))

    plt.xlabel('epoch')
    plt.ylabel('loss')
    plt.legend()
    plt.show()

if __name__ == '__main__':
    main()