import multiprocessing


if __name__ == "__main__":
    # Frozen multiprocessing children re-enter this executable with private
    # Python flags. Handle those before importing or parsing the product CLI.
    multiprocessing.freeze_support()

    from ble_stt.cli import main

    main()
