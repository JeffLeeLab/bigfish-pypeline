# Modified: 2026.01.20
# SNR batch analysis script - simplified version for calculating spot-level SNR

import pathlib
import glob
import signal
import queue
import multiprocessing
import threading
import time
import sys
import yaml
import scipy
import numpy as np
import pandas as pd
import tifffile
import bigfish.stack as stack
import bigfish.detection as detection
import bigfish.plot as plot

# Add src/ to path so bigfish_pypeline package is importable
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[4] / "src"))
from bigfish_pypeline.image_utils import calculate_psf, subtract_background


def compute_snr_spots_individual(
    image,
    spots,
    voxel_size,
    spot_radius
):
    """
    Compute SNR for each individual spot.
    
    Parameters
    ----------
    image : np.ndarray
        Image with shape (z, y, x).
    spots : np.ndarray
        Coordinates of spots with shape (nb_spots, 3) for zyx coordinates.
    voxel_size : tuple
        Voxel size in nanometers (voxel_size_z, voxel_size_yx, voxel_size_yx).
    spot_radius : tuple
        Theoretical spot radius in nanometers (radius_z, radius_yx, radius_yx).
    
    Returns
    -------
    snr_values : np.ndarray
        Array of SNR values for each spot with shape (nb_spots,).
    """
    # Convert spot radius from nm to pixels
    spot_radius_px = detection.get_object_radius_pixel(
        voxel_size_nm=voxel_size,
        object_radius_nm=spot_radius,
        ndim=3
    )
    
    # Define the region sizes for signal and background
    signal_radius = tuple([int(np.ceil(r)) for r in spot_radius_px])
    background_inner_radius = tuple([int(np.ceil(r * 1.5)) for r in spot_radius_px])
    background_outer_radius = tuple([int(np.ceil(r * 2.5)) for r in spot_radius_px])
    
    snr_values = []
    
    for spot_coord in spots:
        z, y, x = int(spot_coord[0]), int(spot_coord[1]), int(spot_coord[2])
        
        # Define bounds for extraction (with boundary checks)
        z_min = max(0, z - background_outer_radius[0])
        z_max = min(image.shape[0], z + background_outer_radius[0] + 1)
        y_min = max(0, y - background_outer_radius[1])
        y_max = min(image.shape[1], y + background_outer_radius[1] + 1)
        x_min = max(0, x - background_outer_radius[2])
        x_max = min(image.shape[2], x + background_outer_radius[2] + 1)
        
        # Extract local region
        local_region = image[z_min:z_max, y_min:y_max, x_min:x_max]
        
        # Create coordinate grids relative to spot center
        zz, yy, xx = np.ogrid[
            z_min-z:z_max-z,
            y_min-y:y_max-y,
            x_min-x:x_max-x
        ]
        
        # Calculate distances (accounting for anisotropic voxels)
        distances = np.sqrt(
            (zz / spot_radius_px[0])**2 + 
            (yy / spot_radius_px[1])**2 + 
            (xx / spot_radius_px[2])**2
        )
        
        # Create masks for signal and background regions
        signal_mask = distances <= 1.0
        background_mask = (distances > 1.5) & (distances <= 2.5)
        
        # Calculate signal and background
        if np.sum(signal_mask) > 0 and np.sum(background_mask) > 0:
            signal = np.mean(local_region[signal_mask])
            background = np.mean(local_region[background_mask])
            background_std = np.std(local_region[background_mask])
            
            # Calculate SNR
            if background_std > 0:
                snr = (signal - background) / background_std
            else:
                snr = 0
        else:
            snr = 0
        
        snr_values.append(snr)
    
    return np.array(snr_values)


def plot_elbow_value(
        images,
        voxel_size=None,
        spot_radius=None,
        log_kernel_size=None,
        minimum_distance=None,
        title=None,
        framesize=(5, 5),
        size_title=20,
        size_axes=15,
        size_legend=15,
        path_output=None,
        ext="png",
        show=True):
    """Plot the elbow curve that allows an automated spot detection.
    
    Modified version that displays the threshold value in the legend.

    Parameters
    ----------
    images : list
        List of ndarrays with shape (z, y, x) or (y, x). The same threshold is
        applied to every images.
    voxel_size : int or float or tuple or list, optional
        Size of a voxel, in nanometer. One value per spatial dimension (zyx or
        yx dimensions). If it's a scalar, the same value is applied to every
        dimensions. Not used if 'log_kernel_size' and 'minimum_distance' are
        provided.
    spot_radius : int or float or tuple or list, optional
        Radius of the spot, in nanometer. One value per spatial dimension (zyx
        or yx dimensions). If it's a scalar, the same radius is applied to
        every dimensions. Not used if 'log_kernel_size' and 'minimum_distance'
        are provided.
    log_kernel_size : int or float or tuple or list, optional
        Size of the LoG kernel. It equals the standard deviation (in pixels)
        used for the gaussian kernel (one for each dimension). One value per
        spatial dimension (zyx or yx dimensions). If it's a scalar, the same
        standard deviation is applied to every dimensions. If None, we estimate
        it with the voxel size and spot radius.
    minimum_distance : int or float or tuple or list, optional
        Minimum distance (in pixels) between two spots we want to be able to
        detect separately. One value per spatial dimension (zyx or yx
        dimensions). If it's a scalar, the same distance is applied to every
        dimensions. If None, we estimate it with the voxel size and spot
        radius.
    title : str, optional
        Title of the plot.
    framesize : tuple, default=(5, 5)
        Size of the frame used to plot with ``plt.figure(figsize=framesize)``.
    size_title : int, default=20
        Size of the title.
    size_axes : int, default=15
        Size of the axes label.
    size_legend : int, default=15
        Size of the legend.
    path_output : str, optional
        Path to save the image (without extension).
    ext : str or list, default='png'
        Extension used to save the plot. If it is a list of strings, the plot
        will be saved several times.
    show : bool, default=True
        Show the figure or not.

    """
    import matplotlib.pyplot as plt
    
    # check parameters
    stack.check_parameter(
        title=(str, list, type(None)),
        framesize=tuple,
        size_title=int,
        size_axes=int,
        size_legend=int,
        path_output=(str, type(None)),
        ext=(str, list),
        show=bool)

    # get candidate thresholds and spots count to plot the elbow curve
    thresholds, count_spots, threshold = detection.get_elbow_values(
        images,
        voxel_size=voxel_size,
        spot_radius=spot_radius,
        log_kernel_size=log_kernel_size,
        minimum_distance=minimum_distance)

    # plot
    plt.figure(figsize=framesize)
    plt.plot(thresholds, count_spots, c="#2c7bb6", lw=2)
    if threshold is not None:
        i_threshold = np.argmax(thresholds == threshold)
        plt.scatter(
            threshold,
            count_spots[i_threshold],
            marker="D",
            c="#d7191c",
            s=60,
            label=f"Selected threshold: {threshold:.2f}")  # MODIFIED: Added threshold value

    # axes
    if title is not None:
        plt.title(title, fontweight="bold", fontsize=size_title)
    plt.xlabel("Thresholds", fontweight="bold", fontsize=size_axes)
    plt.ylabel(
        "Number of mRNAs detected (log scale)",
        fontweight="bold",
        fontsize=size_axes)
    if threshold is not None:
        plt.legend(prop={'size': size_legend})
    plt.tight_layout()
    if path_output is not None:
        # Save the plot
        if isinstance(ext, str):
            ext = [ext]
        for ext_format in ext:
            plt.savefig(f"{path_output}.{ext_format}", dpi=300)
    if show:
        plt.show()
    else:
        plt.close()


def image_processing_function(image_loc, config):
    # Read the image into a numpy array of format ZCYX
    image_name = pathlib.Path(image_loc).stem
    image = tifffile.imread(image_loc)

    print(" ")
    print("Processing: ", image_name)

    # Calculate PSF
    psf_z, psf_yx = calculate_psf(
        config["voxel_size_z"],
        config["voxel_size_yx"],
        config["ex"],
        config["em"],
        config["NA"],
        config["RI"],
        config["microscope"],
    )

    spot_radius_px = detection.get_object_radius_pixel(
        voxel_size_nm=(config["voxel_size_z"], config["voxel_size_yx"], config["voxel_size_yx"]),
        object_radius_nm=(psf_z, psf_yx, psf_yx),
        ndim=3)
    
    # process single spot detection + SNR calculation per channel
    for image_channel in config["channels"]:
        # - - - - - detect spots
        rna = image[:, image_channel, :, :]
        # subtract background
        rna_no_bg = []
        for z in rna:
            z_no_bg = subtract_background(z, config["bg_radius"])
            rna_no_bg.append(z_no_bg)
        rna = np.array(rna_no_bg)

        # LoG filter
        rna_log = stack.log_filter(rna, spot_radius_px)

        # local maximum detection
        mask = detection.local_maximum_detection(
            rna_log, min_distance=spot_radius_px)

        # thresholding
        if config["auto_threshold"] == True:
            elbow_plot_output_path = pathlib.Path(config["output_qc_dir"]).joinpath(
                f"{image_name}_ch{image_channel}_elbow_plot"
            )
            plot_elbow_value(
                rna,
                voxel_size=(
                    config["voxel_size_z"], config["voxel_size_yx"], config["voxel_size_yx"]),
                spot_radius=(psf_z, psf_yx, psf_yx),
                path_output=str(elbow_plot_output_path),
                ext="png",
                show=False
            )
            threshold = detection.automated_threshold_setting(rna_log, mask)
        else:
            if image_channel == config["smFISH_ch1"]:
                threshold = config["smFISH_ch1_thresh"]
            elif image_channel == config["smFISH_ch2"]:
                threshold = config["smFISH_ch2_thresh"]
            else:
                print("smFISH channel and threshold not correctly defined!")

        spots, _ = detection.spots_thresholding(rna_log, mask, threshold)

        print(f"  Channel {image_channel}: {len(spots)} spots detected")

        # - - - - - detect and decompose clusters (for dense region decomposition)
        # get the reference spot
        kernel_size = detection.get_object_radius_pixel(
            voxel_size_nm=(config["voxel_size_z"], config["voxel_size_yx"], config["voxel_size_yx"]),
            object_radius_nm=(psf_z, psf_yx, psf_yx),
            ndim=3
        )
        large_kernel_size = tuple(
            [kernel_size_ * 5 for kernel_size_ in kernel_size])

        rna_denoised = stack.remove_background_gaussian(
            rna, sigma=large_kernel_size)

        reference_spot = detection.build_reference_spot(
            image=rna_denoised,
            spots=spots,
            voxel_size=(config["voxel_size_z"], config["voxel_size_yx"], config["voxel_size_yx"]),
            spot_radius=(psf_z, psf_yx, psf_yx),
            alpha=config["alpha"]
        )

        # decompose dense regions
        sigma_z, sigma_yx, amplitude, background = detection.modelize_spot(
            reference_spot=reference_spot,
            voxel_size=(config["voxel_size_z"], config["voxel_size_yx"], config["voxel_size_yx"]),
            spot_radius=(psf_z, psf_yx, psf_yx)
        )

        regions_to_decompose, spots_out_regions, region_size = detection.get_dense_region(
            image=rna_denoised,
            spots=spots,
            voxel_size=(config["voxel_size_z"], config["voxel_size_yx"], config["voxel_size_yx"]),
            spot_radius=(psf_z, psf_yx, psf_yx),
            beta=config["beta"]
        )

        max_grid = max(200, region_size + 1)
        precomputed_gaussian = detection.precompute_erf(
            ndim = 3,
            voxel_size = (config["voxel_size_z"], config["voxel_size_yx"], config["voxel_size_yx"]),
            sigma = (sigma_z, sigma_yx, sigma_yx),
            max_grid = max_grid
        )

        spots_in_regions, _ = detection.simulate_gaussian_mixture(
            image = rna_denoised,
            candidate_regions = regions_to_decompose,
            voxel_size = (config["voxel_size_z"], config["voxel_size_yx"], config["voxel_size_yx"]),
            sigma = (sigma_z, sigma_yx, sigma_yx),
            amplitude = amplitude,
            background = background,
            precomputed_gaussian = precomputed_gaussian)

        spots_post_decomposition = np.concatenate((spots_out_regions, spots_in_regions[:, :3]), axis=0)

        print(f"  Channel {image_channel}: {len(spots_post_decomposition)} spots after decomposition")

        # - - - - - Calculate SNR for each spot
        print(f"  Calculating SNR for channel {image_channel}...")
        snr_values = compute_snr_spots_individual(
            image=rna,
            spots=spots_post_decomposition,
            voxel_size=(config["voxel_size_z"], config["voxel_size_yx"], config["voxel_size_yx"]),
            spot_radius=(psf_z, psf_yx, psf_yx)
        )

        print(f"  Channel {image_channel}: Mean SNR = {np.mean(snr_values):.2f}, Median SNR = {np.median(snr_values):.2f}")

        # Create array with spots and SNR
        spots_with_snr = np.column_stack([spots_post_decomposition, snr_values])

        # Save as CSV
        csv_output_path = pathlib.Path(config["output_dir"]).joinpath(
            f"{image_name}_ch{image_channel}_spots_snr.csv"
        )
        
        spots_snr_df = pd.DataFrame(
            data = spots_with_snr,
            columns = ["z", "y", "x", "snr"]
        )

        spots_snr_df.to_csv(csv_output_path, index = False)
        print(f"  Saved: {csv_output_path.name}")

        # Optional: plot final detection
        if config.get("save_plots", False):
            final_detection_plot_output = pathlib.Path(config["output_qc_dir"]).joinpath(
                f"{image_name}_ch{image_channel}_finaldetection"
            )
            rna_mip = stack.maximum_projection(rna)
            plot.plot_detection(rna_mip,
                                spots=spots_post_decomposition,
                                radius=spot_radius_px[-1],
                                color="orange",
                                framesize=(20, 16),
                                contrast=True,
                                path_output=str(final_detection_plot_output),
                                ext="png",
                                show=False
                                )


def worker_function(jobs, results):
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    while not jobs.empty():
        try:
            job = jobs.get(block=False)
            results.put(image_processing_function(*job))
        except queue.Empty:
            pass


def main():
    jobs = multiprocessing.Queue()
    results = multiprocessing.Queue()

    # Load the config file
    with open("smFISH_analysis_config.yaml") as fi:
        config = yaml.load(fi, Loader=yaml.Loader)

    # Check if output directories exists; try to create them if they don't
    pathlib.Path(config["output_dir"]).mkdir(exist_ok=True)
    pathlib.Path(config["output_qc_dir"]).mkdir(exist_ok=True)

    # Fill the job queue either with local files identified using the input path pattern
    image_paths = glob.glob(config["input_pattern"])
    
    print(f"Found {len(image_paths)} images to process")
    print(f"Number of workers: {config['number_of_workers']}")
    print(f"Output directory: {config['output_dir']}")
    print("")
    
    for image_path in image_paths:
        jobs.put((image_path, config))

    # Start workers
    workers = []
    for i in range(config["number_of_workers"]):
        p = multiprocessing.Process(
            target=worker_function, args=(jobs, results)
        )
        p.start()
        workers.append(p)

    # Wait for workers to complete
    try:
        for worker in workers:
            worker.join()
    except KeyboardInterrupt:
        for worker in workers:
            worker.terminate()
            worker.join()

    print("\nProcessing complete!")


if __name__ == "__main__":
    # Set the process start method; spawn is default on Windows
    multiprocessing.set_start_method("spawn")
    # Call the main function
    main()
