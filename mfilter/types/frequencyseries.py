"""
Provides a class representing a frequency series.
"""

import numpy as np
from mfilter.types.arrays import Array
from astropy.stats import LombScargle
import matplotlib.pyplot as plt
from pynfft import NFFT, Solver
import scipy.signal as signal


class FrequencySamples(Array):
    def __init__(self, initial_array=None, input_time=None,
                 minimum_frequency=None, maximum_frequency=None,
                 samples_per_peak=None, nyquist_factor=2, n_samples=None,
                 df=None):
        """
        class for creation of frequency samples on regular grid, on custom
        values, using an oversampling factor.

        :param input_time:          Array or array-like
                                    times of the original data
        :param minimum_frequency:   scalar (real)
                                    minimum frequency to compute, default 0
        :param maximum_frequency:   scalar (real)
                                    maximum frequency to compute
        :param samples_per_peak:    integer
                                    number of oversampling per peak, default 5
        :param nyquist_factor:      scalar (real)
                                    value used for estimation of maximum freq.
        :param n_samples:           integer
                                    number of frequencies to compute.
        """
        if initial_array is None:
            if not isinstance(input_time, (np.ndarray, list, Array)):
                raise ValueError("input_time must be an Array or array-like")

            if samples_per_peak is None:
                samples_per_peak = 5

            duration = input_time.max() - input_time.min()

            df = 1 / duration / samples_per_peak

            if minimum_frequency is None:
                minimum_frequency = 0

            if maximum_frequency is None:
                if n_samples is None:
                    # bad estimation of nyquist limit
                    average_nyq = 0.5 * len(input_time) / duration
                    # to fix this bad estimation, amplify by nyquist_factor
                    maximum_frequency = nyquist_factor * average_nyq
                    freq_duration = maximum_frequency - minimum_frequency
                    n_samples = 1 + int(round(freq_duration / df))
            else:
                freq_duration = maximum_frequency - minimum_frequency
                n_samples = 1 + int(round(freq_duration / df))

            initial_array = minimum_frequency + df * np.arange(n_samples)
        else:
            if isinstance(initial_array, FrequencySamples):
                df = initial_array.basic_df
                samples_per_peak = initial_array.samples_per_peak
                initial_array = initial_array.value
            else:
                if df is None:
                    df = initial_array[1] - initial_array[0]
                if samples_per_peak is None:
                    samples_per_peak = 1

        self._df = df
        self._n_per_peak = samples_per_peak
        super().__init__(initial_array)

    def check_nsst(self, B):
        """
        check if the Nyquist-Shannon sampling theorem is satisfied

        :param B: Maximum frequency of interest
        :return: True if the NSST is satisfied
        """
        return 2 * B < self.max()

    def split_by_zero(self):
        """
        split the frequency grid in order to avoid 0 frequency for computation
        of Lomb-Scargle periodogram

        :return:
        """
        idx = self.zero_idx
        if idx is None:
            return None, None
        else:
            return self._data[:idx], self._data[idx+1:]

    def _return(self, ary, **kwargs):
        if isinstance(ary, FrequencySamples):
            return ary

        return FrequencySamples(ary, df=self.basic_df,
                                samples_per_peak=self.samples_per_peak)

    @property
    def has_zero(self):
        return 0 in self._data

    @property
    def zero_idx(self):
        if self.has_zero:
            return np.where(self._data == 0)[0][0]
        else:
            return None

    @property
    def df(self):
        return self._df

    @property
    def samples_per_peak(self):
        return self._n_per_peak

    @property
    def basic_df(self):
        return self._df * self._n_per_peak

    def lomb_scargle(self, times, data, package="astropy", norm="psd"):
        """
        compute the Lomb-Scargle periodogram using astropy package.

        :param times:
        :param data:
        :param package:
        :param norm:
        """
        if package is "astropy":
            lomb = LombScargle(times, data, normalization=norm)
        else:
            raise ValueError("for now we only use astropy package to compute"
                             "lomb-scargle periodogram")

        window = signal.windows.tukey(len(data), alpha=1. / 8)
        data *= window
        W = (window ** 2).sum() / len(window)

        if self.has_zero:
            zero_idx = self.zero_idx
            psd = np.zeros(len(self._data))
            if zero_idx == 0:
                psd[1:] = lomb.power(self._data[1:])
                psd[0] = min(psd[1:])
            else:
                neg_freq, pos_freq = self.split_by_zero()
                right_psd = lomb.power(pos_freq)
                left_psd = lomb.power(np.abs(neg_freq[::-1]))
                psd[:zero_idx] = left_psd[::-1]
                psd[zero_idx] = min(psd[:zero_idx])
                psd[zero_idx+1:] = right_psd
        else:
            psd = lomb.power(np.abs(self._data))

        return FrequencySeries(psd / W, frequency_grid=self, epoch=times.min())

    def lomb_welch(self, times, data, data_per_segment, over):
        """
        compute the Lomb-Scargle average periodogram usign welch computation,
        this method is not developed yet, idea comes from paper:

        Tran Thong, James McNames and Mateo Aboy, "Lomb-Welch Periodogram for
        Non-uniform Sampling", IEEE-EMBS, 26th annual International conference,
        Sep 2004.

        :param times:
        :param data:
        """
        # import pdb
        # pdb.set_trace()
        psd = FrequencySeries(np.zeros(len(self)), frequency_grid=self,
                              epoch=data.epoch)

        counter = 0
        n = 0
        while n < len(data) - data_per_segment:
            aux_timeseries = data.get_time_slice(times[n],
                                                 times[n + data_per_segment])
            window = signal.windows.tukey(len(aux_timeseries), alpha=1. / 8)
            aux_timeseries *= window
            W = (window ** 2).sum() / len(window)
            # W = 1
            psd += (aux_timeseries.psd(self) / W)
            n += int(data_per_segment * over)
            counter += 1

        aux_timeseries = data.get_time_slice(
            times[len(times) - data_per_segment - 1], times[len(times) - 1])
        window = signal.windows.tukey(len(aux_timeseries), alpha=1. / 8)
        aux_timeseries *= window
        W = (window ** 2).sum() / len(window)
        # W = 1
        psd += (aux_timeseries.psd(self) / W)
        counter += 1
        psd /= counter
        return psd


class FrequencySeries(Array):
    def __init__(self, initial_array, frequency_grid=None, delta_f=None,
                 minimum_frequency=None, samples_per_peak=None, epoch=None,
                 dtype=None):
        if len(initial_array) < 1:
            raise ValueError('initial_array must contain at least one sample.')

        if frequency_grid is None:
            if delta_f is None:
                try:
                    delta_f = initial_array.basic_df
                except AttributeError:
                    raise TypeError("must provide either an initial_array "
                                    "with a delta_f attribute, or a value "
                                    "of delta_f")
            if delta_f <= 0:
                raise ValueError('delta_f must be a positive number')

            if minimum_frequency is None:
                try:
                    minimum_frequency = initial_array.min_freq
                except AttributeError:
                    minimum_frequency = 0

            if samples_per_peak is None:
                try:
                    samples_per_peak = initial_array.samples_per_peak
                except AttributeError:
                    samples_per_peak = 1

            # generate synthetic input time of same size as initial_array
            input_times = np.linspace(0, 1/delta_f, len(initial_array))
            frequency_grid = FrequencySamples(input_times,
                                              minimum_frequency=minimum_frequency,
                                              samples_per_peak=samples_per_peak,
                                              n_samples=len(initial_array))
        else:
            try:
                _ = frequency_grid.basic_df
                _ = frequency_grid.min()
                _ = frequency_grid.samples_per_peak
            except AttributeError:
                raise TypeError("must provide either a FrequencySamples object"
                                "as frequency_grid or the parameters necessary"
                                "to compute a frequency grid")

        if epoch is None:
            try:
                epoch = initial_array.epoch
            except AttributeError:
                raise TypeError("must provide either an initial_array with an"
                                "epoch attribute, or a value of epoch")

        assert len(initial_array) == len(frequency_grid)

        super().__init__(initial_array, dtype=dtype)
        self._freqs = frequency_grid
        self._epoch = epoch

    @property
    def frequency_object(self):
        return self._freqs

    @property
    def delta_f(self):
        return self._freqs.df

    @property
    def basic_df(self):
        return self._freqs.basic_df

    @property
    def max_freq(self):
        return self._freqs.max()

    @property
    def min_freq(self):
        return self._freqs.min()

    @property
    def frequencies(self):
        return self._freqs.value

    @property
    def samples_per_peak(self):
        return self._freqs.samples_per_peak

    @property
    def epoch(self):
        return self._epoch

    @property
    def start_time(self):
        return self._epoch

    @property
    def end_time(self):
        return self._epoch + self.duration

    @property
    def duration(self):
        return 1 / self.basic_df

    # def _return(self, ary, **kwargs):
    #     freqs = kwargs.get("frequency_grid", self._freqs)
    #     return FrequencySeries(ary, frequency_grid=freqs,
    #                            epoch=self._epoch, dtype=self.dtype)
    #
    # def _getslice(self, index):
    #     return self._return(self._data[index],
    #                         frequency_grid=self._freqs._getslice(index))

    def __eq__(self, other):
        if super(FrequencySeries, self).__eq__(other):
            return (self._epoch == other.epoch
                    and self.basic_df == other.basic_df)
        else:
            return False

    def reconstruct(self, series, reg=None, times=None):
        if reg is None:
            raise ValueError("to do regression method need a regressor")

        if times is None:
            times = reg.time

        if reg.dict.frequency != self._freqs:
            reg.set_dict(times, self._freqs)
        return reg.reconstruct(series), times

    def inverse_transform(self, reg, times=None):
        if times is not None:
            reg.set_dict(times, self._freqs)
        return reg.get_ft(self)

    def fs_nfft(self, series, times=None):
        if times is None:
            raise ValueError("to do nfft method need a valid TimesSamples")
        plan = NFFT(len(self), len(times))
        plan.x = times.value
        plan.precompute()
        plan.f_hat = series.value
        return plan.trafo(), times

    def to_timeseries(self, method="regression", window=None, **kwargs):
        from mfilter.types.timeseries import TimeSeries, TimesSamples
        if isinstance(window, np.ndarray):
            series = self._return(self._data * window)
        else:
            series = self._return(self._data)

        if method is "regression":

            tmp, times = self.reconstruct(series, reg=kwargs.get("reg", None),
                                          times=kwargs.get("times", None))
            # tmp = self.inverse_transform(reg, times=times)

        elif method is "nfft":
            tmp, times = self.fs_nfft(series, times=kwargs.get("times", None))

        else:
            raise ValueError("for now we have only implemented regressor "
                             "method")

        return TimeSeries(tmp, times=times)

    def match(self, other, psd=None, tol=0.1):
        from mfilter.types import TimeSeries
        from mfilter.filter import match

        if isinstance(other, TimeSeries):
            if abs(other.duration / self.duration - 1) > tol:
                raise ValueError("duration of times is higher than given "
                                 "tolerance")
            other = other.to_frequencyseries()

        assert len(other) == len(self)

        if psd is not None:
            assert len(psd) == len(self)

        return match(self, other, psd=psd)

    def plot(self, axis=None, by_components=True, _show=True,
             label="abs_value"):
        if axis is None:
            fig = plt.figure()
            axis = fig.add_subplot(111)

        if by_components:
            axis.plot(self.frequencies, self.real, label="real part")
            axis.plot(self.frequencies, self.imag, label="imag part")
        else:
            axis.plot(self.frequencies, abs(self), label=label)

        axis.set_title("frequency domain values")
        axis.set_xlabel("frequency")
        axis.legend()
        if _show:
            plt.show()

    def split_values(self):
        return np.hstack((self.real, self.imag))

    # TODO: Not used
    # def frequency_slice(self, start, end):
    #     start_idx = np.argmin(np.abs(self._freqs.offset - start))
    #     end_idx = np.argmin(np.abs(self._freqs.end - end))
    #     return self.slice_by_indexes(start_idx, end_idx), \
    #         self._freqs.slice_by_values(start, end)
    #
    # def almost_equals(self, other):
    #     if isinstance(other, FrequencySeries):
    #         if type(self) != type(other):
    #             return False
    #         if len(self) != len(other):
    #             return False
    #         if self.delta != other.delta:
    #             return False
    #         if self.frequency != other.frequency:
    #             return False
    #         return True
    #     return False
    #
    # def equivalent_freq_series(self, other):
    #     if isinstance(other, FrequencySeries):
    #         if type(self) != type(other):
    #             return False
    #         if self.dtype != other.dtype:
    #             return False
    #         if len(self) != len(other):
    #             return False
    #         if self.delta != other.delta:
    #             return False
    #         if self.frequency != other.frequency:
    #             return False
    #         return True
    #     return False
