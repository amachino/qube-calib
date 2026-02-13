"""Principal-component helpers for complex IQ data."""

from __future__ import annotations

import numpy as np
import numpy.typing as npt


def pca(
    x: npt.NDArray[np.float64],
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    """
    Compute eigenvalues and eigenvectors of covariance-like matrix.

    Parameters
    ----------
    x : NDArray[np.float64]
        Input data matrix.

    Returns
    -------
    tuple[NDArray[np.float64], NDArray[np.float64]]
        Sorted eigenvalues and eigenvectors.
    """
    covariance = np.dot(x, x.transpose()) / x.shape[0]
    eigenvalues, eigenvectors = np.linalg.eig(covariance)
    indices = np.argsort(eigenvalues)
    return eigenvalues[indices], eigenvectors[:, indices]


def to_float(x: npt.NDArray[np.complex128]) -> npt.NDArray[np.float64]:
    """
    Convert complex vector to stacked real/imag representation.

    Parameters
    ----------
    x : NDArray[np.complex128]
        Complex-valued vector.

    Returns
    -------
    NDArray[np.float64]
        Stacked real/imag array with shape `(2, N)`.
    """
    return np.stack([np.real(x), np.imag(x)], axis=0)


def to_complex(x: npt.NDArray[np.float64]) -> npt.NDArray[np.complex128]:
    """
    Convert stacked real/imag representation to complex vector.

    Parameters
    ----------
    x : NDArray[np.float64]
        Stacked real/imag array.

    Returns
    -------
    NDArray[np.complex128]
        Complex-valued vector.
    """
    return np.asarray(x[0, :] + 1j * x[1, :], dtype=np.complex128)


def principal_axis_rotation(
    x: npt.NDArray[np.complex128],
) -> tuple[npt.NDArray[np.complex128], float]:
    """
    Rotate IQ data so the principal component aligns with the imaginary axis.

    Parameters
    ----------
    x : NDArray[np.complex128]
        Complex-valued IQ samples.

    Returns
    -------
    tuple[NDArray[np.complex128], float]
        Rotated IQ samples and principal-axis phase angle.
    """
    float_data = to_float(x)
    center = float_data.mean(axis=1).reshape(float_data.shape[0], 1)
    _, eigenvectors = pca(float_data - center)
    aligned_vectors = (
        eigenvectors if np.dot(center[:, 0], eigenvectors[:, -1]) > 0 else -eigenvectors
    )
    rotated = np.dot(float_data.transpose(), aligned_vectors).transpose()
    angle = np.arctan2(aligned_vectors[0, -1], aligned_vectors[1, -1])
    return to_complex(rotated), float(angle)
